#!/usr/bin/env python3
"""probe_zen_model_list.py — OpenCode Zen 动态免费模型列表可行性探针。

D1 可行性探针前置（设计流程约定）：方案写入文档前用最小脚本验证核心假设。
单遍克制：每个请求最多尝试 2 次（直连失败且属传输层错误时才走一次系统代理回退），
HTTP 状态错误（4xx/5xx）为确定性答案不重试；失败后如需复跑请间隔 >=60s。

探针内容：
  P1  GET https://opencode.ai/zen/v1/models（列表端点，调研确认免鉴权）
      -> 过滤 id 以 `-free` 结尾的免费模型候选池；
      -> 标注 wire-format 排除项（muse-spark* 走 Responses API，非 chat/completions）。
  P2  POST /v1/chat/completions 用**生产同款 body** 实测一个免费模型：
      reasoning_effort="high"、去掉 temperature（对齐 analysis/llm/client.py
      `_apply_provider_body` 对 -free 模型的行为），断言 choices[0].message.content 非空；
      记录 usage 字段存在性（社区 issue #14795 500-bug 类观察点）。

判定：GO = P1 候选池非空 且 P2 内容非空；否则 NO_GO（附原因清单）。
证据链落盘：scripts/probe_zen_results.json（对齐 probe_fm3_results.json 惯例）。
安全：API key 仅掩码输出前 6 字符；结果 JSON 不含 key。
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

ZEN_BASE = "https://opencode.ai/zen/v1"
MODELS_URL = f"{ZEN_BASE}/models"
CHAT_URL = f"{ZEN_BASE}/chat/completions"
# 生产 client.py 对 -free 模型：reasoning_effort=high + 移除 temperature（Zen 网关约束）
CHAT_BODY_BASE = {
    "messages": [{"role": "user", "content": "Reply with exactly: OK"}],
    "max_tokens": 512,
    "reasoning_effort": "high",
}
TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=15.0, pool=15.0)
RESULTS_PATH = Path(__file__).with_name("probe_zen_results.json")
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

# Responses API 格式排除项（2026-08-24 调研：唯一非 chat/completions 的免费模型家族）
RESPONSES_API_PREFIXES = ("muse-spark",)


def load_env_key(name: str) -> str:
    """从 backend/.env 读 KEY=VALUE（独立解析，不依赖 app 导入）。"""
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
        except httpx.TransportError as exc:  # ConnectError/Timeout 等网络层失败才回退
            attempts.append({"trust_env": trust_env, "ok": False, "error": type(exc).__name__,
                             "detail": str(exc)[:200]})
    return None, attempts, "transport_error_both_paths"


def main() -> int:
    result: dict = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "p1_models_list": {},
        "p2_chat_call": {},
        "verdict": "NO_GO",
        "reasons": [],
    }
    zen_key = load_env_key("OPENCODE_ZEN_API_KEY")
    result["zen_key_present"] = bool(zen_key)
    result["zen_key_masked"] = (zen_key[:6] + "...") if zen_key else ""
    auth_headers = {"Authorization": f"Bearer {zen_key}"} if zen_key else {}

    # ---------- P1: 模型列表 ----------
    resp, p1_attempts, p1_err = request_with_proxy_fallback("GET", MODELS_URL, {}, None)
    free_ids: list[str] = []
    all_ids: list[str] = []
    if resp is None:
        result["p1_models_list"] = {"error": p1_err, "attempts": p1_attempts}
        result["reasons"].append("P1 列表端点不可达（直连+代理均传输层失败）")
    elif resp.status_code != 200:
        result["p1_models_list"] = {"status": resp.status_code,
                                    "body_head": resp.text[:300], "attempts": p1_attempts}
        result["reasons"].append(f"P1 列表端点 HTTP {resp.status_code}")
    else:
        try:
            all_ids = [m.get("id", "") for m in resp.json().get("data", [])]
        except Exception as exc:  # noqa: BLE001 - 探针需隔离解析异常
            result["reasons"].append(f"P1 响应非 OpenAI list 格式: {exc!r:.120}")
        free_ids = sorted(m for m in all_ids if m.endswith("-free"))
        eligible = [m for m in free_ids if not m.startswith(RESPONSES_API_PREFIXES)]
        excluded = [m for m in free_ids if m.startswith(RESPONSES_API_PREFIXES)]
        result["p1_models_list"] = {
            "status": 200, "total_models": len(all_ids),
            "free_models": free_ids, "eligible_free_chat": eligible,
            "excluded_responses_api": excluded, "attempts": p1_attempts,
        }
        if not free_ids:
            result["reasons"].append("P1 列表成功但无 -free 模型")

    # ---------- P2: 免费模型 chat 实测（生产同款 body） ----------
    # 设计核心假设即「首选不可用 → 按序重选下一候选」：按序遍历候选池直到首个成功，
    # 上限 MAX_CHAT_ATTEMPTS=3（400 为确定性答案而非限流，无需长退避；克制起见仍设上限）。
    preferred = ["deepseek-v4-flash-free"]
    eligible_pool = [m for m in result["p1_models_list"].get("eligible_free_chat", [])]
    candidates = [m for m in preferred if m in eligible_pool] + \
                 [m for m in eligible_pool if m not in preferred]
    MAX_CHAT_ATTEMPTS = 3

    if not candidates:
        result["p2_chat_call"] = {"skipped": True, "reason": "无可选免费模型"}
        result["reasons"].append("P2 跳过：无 chat/completions 免费模型可测")
    elif not zen_key:
        result["p2_chat_call"] = {"skipped": True, "candidates": candidates,
                                  "reason": "backend/.env 无 OPENCODE_ZEN_API_KEY"}
        result["reasons"].append("P2 跳过：缺少 Zen API key")
    else:
        tried: list[dict] = []
        succeeded: dict | None = None
        for chosen in candidates[:MAX_CHAT_ATTEMPTS]:
            body = dict(CHAT_BODY_BASE, model=chosen)
            resp2, p2_attempts, p2_err = request_with_proxy_fallback(
                "POST", CHAT_URL, {**auth_headers, "Content-Type": "application/json"}, body)
            entry: dict = {"model": chosen, "attempts": p2_attempts}
            if resp2 is None:
                entry.update({"error": p2_err})
                tried.append(entry)
                break  # 传输层双路失败 = 网络问题，换模型无意义
            content = ""
            usage_ok = False
            echoed = None
            if resp2.status_code == 200:
                try:
                    payload = resp2.json()
                except Exception:  # noqa: BLE001
                    payload = {}
                choices = payload.get("choices") or []
                if choices:
                    msg = choices[0].get("message") or {}
                    content = (msg.get("content") or "").strip()
                usage = payload.get("usage")
                usage_ok = isinstance(usage, dict) and bool(usage)
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
            # 4xx/5xx（如 400 Model is unavailable）= 该候选确定性失败 → 试下一候选
        result["p2_chat_call"] = {
            "tried": tried,
            "succeeded_model": (succeeded or {}).get("model"),
            "content_nonempty": bool((succeeded or {}).get("content_nonempty")),
            "usage_present_on_success": (succeeded or {}).get("usage_present"),
        }
        if succeeded is None:
            fail_summary = "; ".join(
                f"{t['model']}→HTTP {t.get('status', t.get('error'))}" for t in tried)
            result["reasons"].append(f"P2 前 {len(tried)} 个候选全部失败: {fail_summary}")

    # ---------- 判定 ----------
    p1_ok = bool(result["p1_models_list"].get("eligible_free_chat"))
    p2 = result["p2_chat_call"]
    p2_ok = bool(p2.get("succeeded_model")) and bool(p2.get("content_nonempty"))
    result["verdict"] = "GO" if (p1_ok and p2_ok) else "NO_GO"

    RESULTS_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[VERDICT] {result['verdict']}  (evidence: {RESULTS_PATH.name})",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
