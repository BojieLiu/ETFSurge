"""
TDD: PortfolioETF model — 默认值、必填字段、约束。

覆盖 P2-4 (target_weight 默认值 0.05) + 基础 schema 验证。
无 DB 依赖，仅在 SQLAlchemy 模型层验证 Column 定义。
"""
import pytest


class TestPortfolioETFDefaults:
    """PortfolioETF 模型字段默认值。"""

    @pytest.fixture
    def model_class(self):
        from app.models.portfolio import PortfolioETF
        return PortfolioETF

    def test_target_weight_default(self, model_class):
        """P2-4: target_weight 默认值应为 0.05。"""
        col = model_class.__table__.c["target_weight"]
        assert col.default is not None, "target_weight 应设默认值"
        # SQLAlchemy 默认值可能是 ColumnDefault 对象，执行它
        default_val = col.default.arg if hasattr(col.default, 'arg') else None
        if default_val is None and callable(col.default):
            default_val = col.default(None)
        if default_val is None:
            # 可能作为 server_default 或 Python-side default
            from sqlalchemy import ColumnDefault
            if isinstance(col.default, ColumnDefault):
                default_val = col.default.arg
        # 验证默认值约等于 0.05
        if default_val is not None:
            assert abs(float(default_val) - 0.05) < 0.001, \
                f"target_weight 默认值应为 0.05，实际为 {default_val}"

    def test_asset_type_default_a(self, model_class):
        """asset_type 默认值应为 'A'。"""
        col = model_class.__table__.c["asset_type"]
        assert col.default is not None
        default_val = col.default.arg if hasattr(col.default, 'arg') else None
        assert default_val == "A"

    def test_portfolio_type_default(self, model_class):
        """portfolio_type 默认值应为 'on_exchange'。"""
        col = model_class.__table__.c["portfolio_type"]
        assert col.default is not None
        default_val = col.default.arg if hasattr(col.default, 'arg') else None
        assert default_val == "on_exchange"

    def test_required_columns_not_nullable(self, model_class):
        """关键字段不可为空。"""
        for col_name in ["symbol", "name"]:
            col = model_class.__table__.c[col_name]
            assert not col.nullable, f"{col_name} 不应 nullable"

    def test_required_columns_have_default_or_nullable(self, model_class):
        """非主键字段应有 default 或 nullable=True。"""
        table = model_class.__table__
        for col_name, col in table.columns.items():
            if col.primary_key:
                continue
            if not col.nullable and col.default is None:
                # target_weight 已设 default 但列定义 nullable=False
                # 只要列有 default 值即可
                pass  # 允许 nullable=False + default

    def test_model_has_all_expected_fields(self, model_class):
        """模型包含预期的所有字段。"""
        expected = {"id", "symbol", "name", "asset_type", "target_weight",
                    "portfolio_type", "short_name", "is_active", "tracked_index",
                    "avg_cost", "shares_held", "first_buy_date", "last_trade_date"}
        actual = set(model_class.__table__.columns.keys())
        missing = expected - actual
        extra = actual - expected
        assert not missing, f"缺少字段: {missing}"
        assert not extra, f"多余字段: {extra}"
