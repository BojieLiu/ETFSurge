#!/usr/bin/env python3
"""probe_openrouter_free_models.py — OpenRouter 免费模型中间层可行性探针。

D1 可行性探针前置：验证「Zen 免费 → OpenRouter 免费 → DeepSeek 付费」三层链的中间层，
并实测「大参数模型优先」选择策略的数据可得性。单遍克制（同 zen 探针约定）：
每请求最多 2 次（直连失败且传输层错误才走一次系统代理回退）；HTTP 状态错误不重试；
复跑间隔 >=60s。

探针内容：
  P0  GET /api/v1/auth/key（带鉴权）——key 层配额/限流事实（免费层 RPM 与日额度的决定性证据）。
  P1  GET /api/v1/models（公开）——过滤免费池（pricing.prompt=="0" ∧ pricing.completion=="0"）；
      对每个免费模型做**参数量启发式**抽取（id+name+description 中 `数字+B` 模式，取最大值），
      统计覆盖率——直接回答「大参优先是否可行」的数据可得性问题。
  P2  POST /api/v1/chat/completions 按参数量降序实测前 MAX_CHAT_ATTEMPTS=3 个候选
      （标准 OpenAI 格式；200 ∧ content 非空才算成功），验证可用性与延迟。

判定：GO = P1 免费池非空 ∧ P2 至少一个候选内容非空。
证据落盘：scripts/probe_openrouter_results.json。API key 仅掩码输出，不入结果 JSON 值域。
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

OR_BASE = "https://openrouter.ai/api/v1"
KEY_URL = f"{OR_BASE}/auth/key"
MODELS_URL = f"{OR_BASE}/models"
CHAT_URL = f"{OR_BASE}/chat/completions"
CHAT_HEADERS_EXTRA = {"Content-Type": "application/json", "X-Title": "ETF-Surge-Probe"}
CHAT_BODY_BASE = {
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    "max_tokens": 1024,
}
TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=15.0, pool=15.0)
MAX_CHAT_ATTEMPTS = 3
RESULTS_PATH = Path(__file__).with_name("probe_openrouter_results.json")
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
# 参数量启发式：匹配 "70B"/"8x22b"/"235b"/"0.6B" 等 token；负向断言排除 "Built"/"8bit" 等
PARAM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z0-9])")
DESC_SLICE = 400  # description 只取头部参与启发式，控噪


def load_env_key(name: str) -> str:
    if not ENV_PATH.exists():
        return ""
    for line in ENV_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def request_with_proxy_fallback(method: str, url: str, headers: dict, json_body: dict | None):
    """直连优先（生产 trust_env=False 同款）；仅传输层错误时代理回退一次。"""
    attempts = []
    for trust_env in (False, True):
        try:
            t0 = time.perf_counter()
            with httpx.Client(trust_env=trust_env, timeout=TIMEOUT) as client:
                resp = client.request(method, url, headers=headers, json=json_body)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            attempts.append({"trust_env": trust_env, "ok": True,
                             "status": resp.status_code, "elapsed_ms": round(elapsed_ms)})
            return resp, attempts, None
        except httpx.TransportError as exc:
            attempts.append({"trust_env": trust_env, "ok": False,
                             "error": type(exc).__name__, "detail": str(exc)[:200]})
    return None, attempts, "transport_error_both_paths"


def extract_param_estimate(*texts: str) -> tuple[float | None, str]:
    """从若干文本中抽参数量估计（取最大匹配，MoE 场景近似总参）。返回 (估计值B, 命中片段)。"""
    best, hit = None, ""
    for text in texts:
        if not text:
            continue
        for m in PARAM_RE.finditer(text):
            try:
                val = float(m.group(1))
            except ValueError:  # pragma: no cover - 正则保证可转 float
                continue
            if val > 0 and (best is None or val > best):
                best, hit = val, m.group(0)
    return best, hit


def main() -> int:
    result: dict = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "p0_key_info": {},
        "p1_free_pool": {},
        "p2_chat_calls": {},
        "verdict": "NO_GO",
        "reasons": [],
    }
    or_key = load_env_key("OPENROUTER_API_KEY")
    result["or_key_present"] = bool(or_key)
    result["or_key_masked"] = (or_key[:9] + "...") if or_key else ""
    auth_headers = {"Authorization": f"Bearer {or_key}"} if or_key else {}

    # ---------- P0: key 配额 ----------
    if or_key:
        resp, att, err = request_with_proxy_fallback("GET", KEY_URL, auth_headers, None)
        entry = {"attempts": att}
        if resp is None:
            entry["error"] = err
        elif resp.status_code != 200:
            entry.update({"status": resp.status_code, "body_head": resp.text[:300]})
        else:
            data = {}
            try:
                data = resp.json().get("data", {}) or {}
            except Exception:  # noqa: BLE001 - 探针需隔离解析异常
                pass
            entry.update({
                "status": 200,
                "is_free_tier": data.get("is_free_tier"),
                "limit": data.get("limit"),
                "usage": data.get("usage"),
                "limit_remaining": data.get("limit_remaining"),
                "rate_limit": data.get("rate_limit"),
            })
        result["p0_key_info"] = entry
    else:
        result["reasons"].append("backend/.env 无 OPENROUTER_API_KEY")

    # ---------- P1: 免费池 + 参数量启发式 ----------
    resp, p1_att, p1_err = request_with_proxy_fallback("GET", MODELS_URL, {}, None)
    free_rows: list[dict] = []
    total = 0
    if resp is None:
        result["p1_free_pool"] = {"error": p1_err, "attempts": p1_att}
        result["reasons"].append("P1 模型列表不可达（直连+代理均传输层失败）")
    elif resp.status_code != 200:
        result["p1_free_pool"] = {"status": resp.status_code,
                                  "body_head": resp.text[:300], "attempts": p1_att}
        result["reasons"].append(f"P1 模型列表 HTTP {resp.status_code}")
    else:
        rows = []
        try:
            rows = resp.json().get("data", []) or []
        except Exception as exc:  # noqa: BLE001
            result["reasons"].append(f"P1 响应非预期 JSON: {exc!r:.120}")
        total = len(rows)
        for m in rows:
            pricing = m.get("pricing") or {}
            if str(pricing.get("prompt")) == "0" and str(pricing.get("completion")) == "0":
                mid = m.get("id", "")
                name = m.get("name", "")
                desc = (m.get("description") or "")[:DESC_SLICE]
                est, hit = extract_param_estimate(mid, name, desc)
                ctx = m.get("context_length") or m.get("top_provider", {}).get("context_length")
                free_rows.append({
                    "id": mid,
                    "name": name,
                    "context_length": ctx,
                    "param_estimate_b": est,
                    "param_hit_token": hit,
                    "supported_parameters_count": len(m.get("supported_parameters") or []),
                })
        with_size = [r for r in free_rows if r["param_estimate_b"] is not None]
        free_rows.sort(key=lambda r: (
            r["param_estimate_b"] is None,
            -(r["param_estimate_b"] or 0.0),
            -(r["context_length"] or 0),
        ))
        result["p1_free_pool"] = {
            "status": 200, "total_models": total, "free_count": len(free_rows),
            "size_heuristic_coverage": f"{len(with_size)}/{len(free_rows)}",
            "ranked_top15": free_rows[:15],
            "attempts": p1_att,
        }
        if not free_rows:
            result["reasons"].append("P1 列表成功但免费池为空")

    candidates = [r["id"] for r in free_rows]

    # ---------- P2: 大参优先逐个实测 ----------
    tried: list[dict] = []
    succeeded: dict | None = None
    if not candidates:
        result["p2_chat_calls"] = {"skipped": True, "reason": "免费池为空"}
    elif not or_key:
        result["p2_chat_calls"] = {"skipped": True, "candidates": candidates[:MAX_CHAT_ATTEMPTS],
                                   "reason": "缺少 OPENROUTER_API_KEY"}
    else:
        for model_id in candidates[:MAX_CHAT_ATTEMPTS]:
            body = dict(CHAT_BODY_BASE, model=model_id)
            resp2, att2, err2 = request_with_proxy_fallback(
                "POST", CHAT_URL, {**auth_headers, **CHAT_HEADERS_EXTRA}, body)
            entry = {"model": model_id, "attempts": att2}
            if resp2 is None:
                entry["error"] = err2
                tried.append(entry)
                break  # 传输层双路失败=网络问题，换模型无意义
            content, usage_ok, echoed = "", False, None
            if resp2.status_code == 200:
                try:
                    payload = resp2.json()
                except Exception:  # noqa: BLE001
                    payload = {}
                choices = payload.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = (msg.get("content") or "").strip()
                usage_ok = isinstance(payload.get("usage"), dict) and bool(payload.get("usage"))
                echoed = payload.get("model")
            entry.update({
                "status": resp2.status_code,
                "content_nonempty": bool(content),
                "content_head": content[:80],
                "usage_present": usage_ok,
                "echoed_model": echoed,
                "error_body_head": None if resp2.status_code == 200 else resp2.text[:300],
            })
            tried.append(entry)
            if resp2.status_code == 200 and content:
                succeeded = entry
                break
        result["p2_chat_calls"] = {
            "tried": tried,
            "succeeded_model": (succeeded or {}).get("model"),
            "content_nonempty": bool((succeeded or {}).get("content_nonempty")),
            "latency_note": next(
                (a.get("elapsed_ms") for t in tried if t.get("model") == (succeeded or {}).get("model")
                 for a in t.get("attempts", []) if a.get("ok")), None),
        }
        if succeeded is None:
            fail_summary = "; ".join(
                f"{t['model']}→{t.get('status', t.get('error'))}" for t in tried)
            result["reasons"].append(f"P2 前 {len(tried)} 个候选全部失败: {fail_summary}")

    # ---------- 判定 ----------
    p1_ok = bool(free_rows)
    p2_ok = bool(result["p2_chat_calls"].get("succeeded_model"))
    result["verdict"] = "GO" if (p1_ok and p2_ok) else "NO_GO"

    RESULTS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items()}, ensure_ascii=False, indent=2))
    print(f"\n[VERDICT] {result['verdict']}  (evidence: {RESULTS_PATH.name})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
