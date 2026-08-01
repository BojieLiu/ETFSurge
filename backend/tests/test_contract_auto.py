# -*- coding: utf-8 -*-
"""T11: 契约自动化校验（G6）——契约文件声明的路由必须真实存在；前端 marketApi 方法指向的路由必须存在。

- 解析 api-contracts/**/*.md 中的 `(GET|POST|PUT|DELETE|WS) /api/v1/...` 声明
- 断言每个声明路径已注册到 FastAPI app（防「契约有、后端无」漂移）
- 解析 frontend/src/api/index.js 的 URL 模板，断言路由存在（防「前端方法指向不存在路由」）
"""
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app

ROOT = Path(__file__).resolve().parent.parent.parent
CONTRACTS_DIR = ROOT / "api-contracts"
FRONTEND_API = ROOT / "frontend" / "src" / "api" / "index.js"

# WS 端点白名单（契约中的 WS 路径）
_WS_PATHS = {
    "/api/v1/ws/market/{symbol}",
    "/api/v1/ws/news",
    "/api/v1/ws/portfolio",
    "/api/v1/ws/task-notifications",
    "/api/v1/ws/design-report/{session_id}",
    "/ws/market/{symbol}",
    "/ws/news",
    "/ws/portfolio",
    "/ws/task-notifications",
    "/ws/design-report/{session_id}",
}


def _registered_paths() -> set[str]:
    """遍历各 router 模块收集真实注册路径。

    注意：新版 FastAPI 的 app.routes 含 _IncludedRouter 惰性占位（path=None），
    直接遍历拿不到路由——必须遍历各 router 模块的 APIRoute。
    """
    paths = {"/health"}
    from app.routers import market, portfolio, analysis, news, ws, admin, factors, system
    for mod in (market, portfolio, analysis, news, ws, admin, factors, system):
        for route in mod.router.routes:
            p = getattr(route, "path", "")
            if p:
                paths.add(p)
    return paths


def _norm_template(path: str) -> str:
    """路径占位符归一化：任意 {..} / <..> / :x / ${..} → {x}；剥离 ?query 与中文注记。"""
    path = path.split("?")[0]  # 剥离 query 示例（如 ?keyword=茅台）
    path = re.split(r"[（(]", path)[0]  # 剥离中文/英文注记（如「（已废弃」）
    path = path.replace("${", "{")
    path = re.sub(r"<[^>]+>", "{x}", path)
    path = re.sub(r"\{[^}]*\}", "{x}", path)  # {id}/{item_id} 统一
    path = re.sub(r":([A-Za-z_][A-Za-z0-9_]*)", "{x}", path)
    return path.rstrip("/")


def _contract_paths() -> list[tuple[str, str, str]]:
    """扫描契约文件，返回 [(method, path, source_file)]。"""
    found: list[tuple[str, str, str]] = []
    if not CONTRACTS_DIR.exists():
        return found
    for md in CONTRACTS_DIR.rglob("*.md"):
        if md.name == "contract_template.md":  # 模板占位非真实契约
            continue
        text = md.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"(GET|POST|PUT|DELETE|WS)\s+(/api/v1/[^\s`]+|/ws/[^\s`]+)", text):
            method, path = m.group(1), m.group(2).rstrip("`")
            found.append((method, path, md.name))
    return found


def test_contract_routes_registered():
    """契约声明的每条路由都已注册到后端（禁止「契约有、后端无」）。"""
    registered = {_norm_template(p) for p in _registered_paths()}
    ws = {_norm_template(p) for p in _WS_PATHS}
    missing = []
    for method, path, src in _contract_paths():
        norm = _norm_template(path)
        if norm in ws or norm in registered:
            continue
        missing.append(f"{method} {path} ({src})")
    assert not missing, f"契约声明但后端未注册:\n" + "\n".join(missing[:10])


def test_frontend_api_urls_registered():
    """前端 api/index.js 的 URL 模板指向的路由必须存在（防隐藏断裂）。"""
    if not FRONTEND_API.exists():
        pytest.skip("frontend/src/api/index.js 不存在")
    registered = {_norm_template(p) for p in _registered_paths()}
    text = FRONTEND_API.read_text(encoding="utf-8", errors="ignore")
    urls = re.findall(r"['`](/api/v1/[^'`?$]+)['`]", text)
    missing = []
    for u in sorted(set(urls)):
        norm = _norm_template(u)
        if norm not in registered:
            missing.append(u)
    assert not missing, f"前端方法指向未注册路由:\n" + "\n".join(missing[:10])


def test_contract_has_frontend_backend_checklist():
    """契约文件应含 Frontend-Backend Checklist（流程强制项）。"""
    if not CONTRACTS_DIR.exists():
        pytest.skip("api-contracts 不存在")
    checked = 0
    for md in CONTRACTS_DIR.rglob("*.md"):
        text = md.read_text(encoding="utf-8", errors="ignore")
        if "Frontend-Backend Checklist" in text or "前后端检查表" in text:
            checked += 1
    assert checked >= 10, f"契约文件含检查表的仅 {checked} 份"
