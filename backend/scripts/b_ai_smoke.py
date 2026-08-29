"""b.ai 生产启用验证 - 最小化 4 步 (无 token 消费, 纯连通性).

1. 检查 B_AI_API_KEY 已配
2. 检查代理可达 (7897)
3. HTTPS GET /v1/models (鉴权, 不消费 token)
4. 报告: key 有效/无效 + 模型白名单校验

用法: cd backend && python -W ignore scripts/b_ai_smoke.py
"""
import os
import sys
import json
import urllib.request
import urllib.error
from pathlib import Path


def load_dotenv() -> None:
    """轻量 .env 解析 (避免依赖 pydantic / settings)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def check_proxy(proxy_url: str) -> tuple[bool, str]:
    """检查代理端口可达. 失败 → (False, msg)."""
    try:
        from urllib.parse import urlparse
        u = urlparse(proxy_url)
        host = u.hostname or "127.0.0.1"
        port = u.port or 7897
        import socket
        with socket.create_connection((host, port), timeout=2):
            return True, f"{host}:{port} OK"
    except Exception as e:
        return False, f"{proxy_url} unreachable: {type(e).__name__}: {e}"


def list_models(api_url: str, api_key: str, proxy_url: str | None) -> tuple[int, str, dict | None]:
    """GET {api_url 父}/models. 返 (status, body, json)."""
    from urllib.parse import urlparse
    u = urlparse(api_url)
    models_url = f"{u.scheme}://{u.netloc}/v1/models"
    req = urllib.request.Request(models_url, headers={
        "Authorization": f"Bearer {api_key}",
    })
    proxy_handler = urllib.request.ProxyHandler({
        "http": proxy_url, "https": proxy_url,
    } if proxy_url else {})
    opener = urllib.request.build_opener(proxy_handler)
    try:
        with opener.open(req, timeout=10) as resp:
            data = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, data, json.loads(data)
            except json.JSONDecodeError:
                return resp.status, data, None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), None
    except urllib.error.URLError as e:
        return 0, f"URLError: {e}", None
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", None


def main() -> int:
    load_dotenv()
    key = os.environ.get("B_AI_API_KEY", "").strip()
    url = os.environ.get("B_AI_API_URL", "https://api.b.ai/v1/chat/completions").strip()
    proxy = os.environ.get("B_AI_PROXY_URL", "").strip() or None
    allowed = os.environ.get("B_AI_ALLOWED_MODELS", "").strip()

    print("=== b.ai 生产启用验证 ===\n")
    print(f"1. B_AI_API_KEY configured: {bool(key)} (len={len(key)})")
    if not key:
        print("\n[FAIL] B_AI_API_KEY 未配. 在 backend/.env 写入:")
        print("B_AI_API_KEY=sk-...")
        return 1

    print(f"2. B_AI_API_URL = {url}")
    print(f"3. B_AI_PROXY_URL = {proxy}")
    print(f"4. B_AI_ALLOWED_MODELS = {allowed}\n")

    # 代理检查
    print("[Step 1] 代理可达性检查...")
    ok, msg = check_proxy(proxy or "http://127.0.0.1:7897")
    print(f"  {msg}")
    if not ok:
        print(f"\n[FAIL] 代理不可达, b.ai 不会工作. 请检查 Clash 是否启动.")
        return 1

    # models 端点
    print("\n[Step 2] GET /v1/models (鉴权, 无 token 消费)...")
    status, body, j = list_models(url, key, proxy)
    print(f"  HTTP {status}")
    if j and "data" in j:
        models = [m.get("id", "?") for m in j["data"]]
        print(f"  available models: {len(models)}")
        for m in models[:20]:
            mark = "  OK" if m in allowed.split(",") else "  --"
            print(f"   - {m}{mark if m in allowed.split(',') else ''}")
        # 白名单校验
        allowed_list = [s.strip() for s in allowed.split(",") if s.strip()]
        not_in_catalog = [m for m in allowed_list if m not in models]
        if not_in_catalog:
            print(f"\n[WARN] 白名单 {not_in_catalog} 在 /models 不存在, 调用必失败")
            print("        建议: 从 B_AI_ALLOWED_MODELS 移除, 或确认模型 ID 大小写")
        else:
            print(f"\n[OK] 白名单 {allowed_list} 全部在 /models 中")
        return 0
    elif status == 401:
        print(f"\n[FAIL] 401 Unauthorized - key 无效或过期. body={body[:200]}")
        return 1
    elif status == 403:
        print(f"\n[FAIL] 403 Forbidden - key 被禁或区域受限. body={body[:200]}")
        return 1
    else:
        print(f"\n[FAIL] HTTP {status} body={body[:300]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
