"""
O6 (docs/archived/round7-rediagnosis.md §7 P8): /factors/model 补输出 valid/no_data/warn/static 聚合汇总。

P8 问题: /factors/active 有 summary（valid/warn/no_data/static/avg_ic），但 /factors/model
端点只输出 total/categories/updated_at——前端无法直接读取模型健康度（实测 summary=null）。

修复: /factors/model 复用与 /factors/active 相同的状态判定（_status_of 逻辑），
在响应体补 summary 聚合字段。
"""

from fastapi.testclient import TestClient
from app.main import app


client = TestClient(app)


class TestFactorModelSummary:
    def test_model_has_summary(self):
        """GET /factors/model 响应含 summary（valid/warn/no_data/static/avg_ic）。"""
        resp = client.get("/api/v1/factors/model")
        assert resp.status_code == 200
        body = resp.json()
        assert "summary" in body, "/factors/model 缺 summary 字段"
        s = body["summary"]
        for key in ("valid", "warn", "no_data", "static", "avg_ic"):
            assert key in s, f"summary 缺 {key}"
        assert isinstance(s["valid"], int)
        assert isinstance(s["warn"], int)
        assert isinstance(s["no_data"], int)
        assert isinstance(s["static"], int)
        assert s["avg_ic"] is None or isinstance(s["avg_ic"], float)

    def test_model_summary_counts_total(self):
        """summary 覆盖 computable 因子，与 /factors/active 同口径（≤ total 全量 YAML 因子）。"""
        resp = client.get("/api/v1/factors/model")
        body = resp.json()
        s = body["summary"]
        assert s["valid"] + s["warn"] + s["no_data"] + s["static"] <= body["total"], \
            f"{s} vs total={body['total']}"
        # 与 /factors/active 的 summary 完全一致（同口径复用）
        active = client.get("/api/v1/factors/active").json()
        assert s == active["summary"], f"model summary {s} 与 active summary {active['summary']} 不一致"

    def test_model_categories_unchanged(self):
        """补 summary 不影响既有 categories 结构（向后兼容）。"""
        resp = client.get("/api/v1/factors/model")
        body = resp.json()
        assert isinstance(body["categories"], list)
        assert all("name" in c and "count" in c and "subcategories" in c
                   for c in body["categories"])
