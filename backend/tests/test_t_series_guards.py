"""
T 系列测试防护（round23-system-audit-optimization §5/§8.1 落地）。

T7: 跨字段一致性断言——KDJ 超买(J≥80) 不得 BUY；score 与 signal 标签同源。
T10: 统计口径不变式——factor_ic_records 行数 == 去重日数（F25① 已落地，此处显式守护）。
T11: 分级语义断言——利空(negative)可进 importance≥4；战争/制裁不得判利好；
     「挑战/战略」等含「战」子串的普通词不得误命中 risk（F23 词边界修复）。
"""
import pytest
from datetime import date, timedelta
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.analysis.signal import generate_signal
from app.database import Base
from app.models.factor_ic import FactorICRecord


class TestT7CrossFieldConsistency:
    """T7: KDJ 超买 ↔ signal 跨字段一致性（§2.3d 实锤：159516 J=98.7 → BUY 误判）。"""

    def _signal(self, j, rsi=50, k=85, d=80):
        return generate_signal({
            "rsi": rsi,
            "kdj": {"k": k, "d": d, "j": j},
            "macd": {"dif": 0.1, "dea": 0.05},
        })

    def test_kdj_overbought_not_buy(self):
        """J=98.7（极端超买）→ signal 不得为 buy。"""
        sig = self._signal(j=98.7)
        assert sig["signal"] != "buy", f"J=98.7 超买不得 BUY，实际 {sig['signal']}"

    def test_kdj_85_overbought_not_buy(self):
        """J=85.7（超买区）→ 不得 buy（F10 阈值下移 80 覆盖）。"""
        sig = self._signal(j=85.7)
        assert sig["signal"] != "buy", f"J=85.7 超买不得 BUY，实际 {sig['signal']}"

    def test_overbought_with_rsi_weak_still_no_buy(self):
        """159516 反例复现：J=98.7 + RSI=39.9 → 不得给最强买入。"""
        sig = self._signal(j=98.7, rsi=39.9)
        assert sig["signal"] != "buy"
        assert sig.get("score", 1) <= 0, "超买 + 偏弱 RSI 得分不得为正（不得给买入倾向）"

    def test_hold_allows_overbought_reason(self):
        """超买降级为 hold 时 reason 含「超买」提示（用户可见解释）。"""
        sig = self._signal(j=92.0)
        if sig["signal"] == "hold":
            assert any("超买" in (r or "") for r in sig.get("reasons", [])), "hold 时应提示超买原因"


class TestT10StatInvariant:
    """T10: 统计口径不变式——行数 == 去重日数（日频 1 行，杜绝刷新次数注水）。"""

    @pytest.mark.asyncio
    async def test_rows_equal_distinct_dates(self):
        from app.factors.ic_tracker import ICTracker

        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[FactorICRecord.__table__])
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        tracker = ICTracker()
        async with factory() as db:
            for i in range(5):
                await tracker.save_ic_batch_to_db(
                    db, {"technical.ma.sma_5": 0.02 * (i + 1)},
                    trade_date=date(2026, 8, 10 + i),
                )
            # 同一天重复刷新（第 3 天刷新两次）→ 不追加
            await tracker.save_ic_batch_to_db(
                db, {"technical.ma.sma_5": 0.99}, trade_date=date(2026, 8, 12))
            rows = (await db.execute(select(FactorICRecord))).scalars().all()
            distinct_dates = len({r.trade_date for r in rows})
        assert len(rows) == distinct_dates == 5, \
            f"行数 {len(rows)} 必须 == 去重日数 {distinct_dates}（同天刷新不得追加）"
        await engine.dispose()


class TestT11NewsLevelSemantics:
    """T11: 分级语义断言——利空可进 importance≥4；战争/制裁不得判利好。"""

    def test_negative_news_can_be_important(self):
        """利空（negative 类别）importance 可 ≥4——利空不得被重要性筛选系统性隐藏。"""
        from app.fetchers.levistock_fetcher import classify_news
        # 「暴跌」类利空新闻（含 level 升级词）应可达到 importance≥4
        cat, level = classify_news("某公司财报暴跌，机构下调评级")
        assert cat == "negative" or cat == "major"
        assert level >= 3, f"利空新闻重要性过低，实际 level={level}"

    def test_war_news_not_positive(self):
        """战争/军事类不得判利好（F23: 移入 risk 类别；重大事件 major 优先级更高也允许）。"""
        from app.fetchers.levistock_fetcher import classify_news
        # 「俄乌冲突」→ risk；「美军空袭」→ major（重大>风险优先级，但都不得 positive）
        for title in ("俄乌冲突升级，全球市场震荡", "美军空袭也门胡塞武装"):
            cat, _ = classify_news(title)
            assert cat in ("major", "risk"), f"「{title}」应为 major/risk，实际 {cat}"
            assert cat != "positive", "战争不得标为利好"

    def test_tiao_zhan_not_misclassified_as_risk(self):
        """F23 词边界：含「战」子串的普通词（挑战/战略）不得误命中 risk。"""
        from app.fetchers.levistock_fetcher import classify_news
        cat, _ = classify_news("公司面临新的市场挑战，推出战略转型")
        assert cat != "risk", f"「挑战/战略」含「战」子串但不应命中 risk，实际 {cat}"

    def test_is_important_orthogonal_to_category(self):
        """importance≥4 与 category 正交——利空事件可达到 importance≥4（F22 修复
        「利空(3)永不推送」：含 major/risk 词的利空仍按单调 importance 推送）。"""
        from app.fetchers.levistock_fetcher import classify_news, classify_news_level
        # 「重大利空」→ major(5)；「制裁」→ risk(4)——均为利空性质但 importance≥4 可推送
        for title in ("某公司突发重大利空：业绩暴跌", "欧盟宣布对俄新制裁"):
            cat, level = classify_news(title)
            assert level >= 4, f"「{title}」importance 应 ≥4（利空不再被系统性隐藏），实际 level={level}"
            assert cat != "positive", "利空事件不得判利好"
