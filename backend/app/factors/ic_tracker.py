"""
ICTracker: Information Coefficient tracking for factor evaluation.

Provides Spearman rank IC computation, multi-period IC series, ICIR,
and half-life estimation. Used to validate factor efficacy before
including them in portfolio design weights.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sqlalchemy import func, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.factor_values import is_meaningful_value  # FS1: 零值判定单点

logger = logging.getLogger(__name__)


def _beijing_today() -> Any:
    """F25①: 交易日取北京时间（UTC+8）——容器 TZ 未设时进程为 UTC，直接 utcnow()
    会把交易日算成前一天，且与 news 时间戳时区修复（F24）口径不一致。"""
    return (datetime.now(timezone.utc) + timedelta(hours=8)).date()


def _newey_west_se(values: np.ndarray, lag: int = 1) -> float:
    """Newey-West 标准误（lag=1，日频 IC 自相关调整）。

    文档 F25②: naive √T 低估日频 IC 自相关导致的 SE，t 检验需 NW 调整。
    var_nw = γ0 + 2·Σ_{l=1..lag} (1 - l/(lag+1))·γl，其中 γl = (1/T)Σ u_t·u_{t-l}。
    """
    n = len(values)
    mean = float(values.mean())
    resid = values - mean
    var = float((resid ** 2).sum()) / n
    for l in range(1, lag + 1):
        cov = float((resid[:-l] * resid[l:]).sum()) / n
        var += 2.0 * (1.0 - l / (lag + 1.0)) * cov
    if var <= 0:
        return 0.0
    return float(np.sqrt(var / n))


def compute_series_stats(ic_values: list[float]) -> dict[str, float | None] | None:
    """F25②: IC 序列统计——IC_mean/IC_std/IR/t（Newey-West lag=1 SE）。

    业内判据（docs/round23 §8 F25②）:
    - IC_mean = mean(ic)；IC_std = std(ic)（样本标准差）
    - IR = IC_mean / IC_std；t = IC_mean / SE(NW) （等价 IC_mean×√T/IC_std_NW）
    - 有效需 t≥2 且 |IR|≥0.5，样本 ≥ MIN_TRADING_DAYS。

    Returns:
        {"ic_mean","ic_std","ir","t_stat"}（ir 可为 None——恒常序列无 IR）或 None。
    """
    arr = np.asarray([float(v) for v in ic_values if v is not None and v == v], dtype=float)
    if len(arr) < 2:
        return None
    ic_mean = float(arr.mean())
    ic_std = float(arr.std(ddof=1))
    if ic_std == 0:
        # 恒常 IC 序列：无方差 → IR 无定义、t=0（不显著），不抛异常
        return {"ic_mean": round(ic_mean, 4), "ic_std": 0.0, "ir": None, "t_stat": 0.0}
    ir = ic_mean / ic_std
    se = _newey_west_se(arr, lag=1)
    if se > 0:
        t_stat = ic_mean / se
    else:
        t_stat = float("inf") if ic_mean != 0 else 0.0
    return {
        "ic_mean": round(ic_mean, 4),
        "ic_std": round(ic_std, 4),
        "ir": round(ir, 4),
        "t_stat": round(t_stat, 4),
    }


def build_forward_returns(
    market_data: dict[str, dict[str, Any]],
    symbols: list[str] | None = None,
    window: int = 1,
) -> pd.Series:
    """Build forward returns from market_data close price series.

    Uses the close price history to compute (close[0] - close[window]) / close[window],
    where index 0 is the most recent.

    Args:
        market_data: {symbol: {close: [float, ...]}} with close prices (recent first).
        symbols: Optional subset of symbols to compute (default: all).
        window: Forward return window in periods (1 = next period return).

    Returns:
        pd.Series: {symbol: forward_return} for symbols with sufficient data.
    """
    targets = symbols if symbols is not None else list(market_data.keys())
    returns: dict[str, float] = {}
    for sym in targets:
        data = market_data.get(sym, {})
        close = data.get("close", [])
        if not isinstance(close, (list, tuple)) or len(close) < window + 1:
            continue
        try:
            cur = float(close[0])
            fut = float(close[window])
            if fut != 0:
                returns[sym] = (cur - fut) / fut
        except (TypeError, ValueError, IndexError):
            continue
    return pd.Series(returns)


class ICTracker:
    """Information Coefficient tracker for factor evaluation.

    IC = Spearman rank correlation between factor values and forward returns.
    ICIR = mean(IC) / std(IC) — measures consistency.
    """

    def __init__(self):
        self._records: list[dict[str, Any]] = []

    def compute_ic(self, factor_values: pd.Series, forward_returns: pd.Series) -> float | None:
        """Compute single-period Spearman rank IC.

        Args:
            factor_values:   Factor values across assets in period t.
            forward_returns: Forward returns (e.g. t+1) for the same assets.

        Returns:
            Spearman rank correlation coefficient, or None when the IC is
            undefined (insufficient samples / constant input / NaN) —
            U3/N06: None 语义表示"该因子本批不可计算"，调用方跳过而非写 0。
        """
        combined = pd.concat([factor_values, forward_returns], axis=1).dropna()
        if len(combined) < 3:
            return None
        vals = combined.iloc[:, 0]
        rets = combined.iloc[:, 1]
        # U3/N06: 常量输入检测——spearmanr 对常量序列产生 ConstantInputWarning + NaN，
        # 旧代码把 NaN 转 0.0，全 0 批次覆盖 _last_ic_batch → IC 数据永久丢失（Z06/N06）。
        if vals.nunique() == 1 or rets.nunique() == 1:
            return None
        corr, _ = spearmanr(vals, rets)
        if np.isnan(corr):
            return None
        return float(corr)

    def compute_ic_series(
        self,
        factor_values: pd.DataFrame,
        forward_returns: pd.DataFrame,
    ) -> pd.Series:
        """Compute IC series across multiple time periods.

        Args:
            factor_values:   DataFrame(T, N) — factor values at each period.
            forward_returns: DataFrame(T, N) — forward returns for each period.

        Returns:
            Series(T) of IC values per period.
        """
        ic_values = []
        for idx in factor_values.index:
            if idx not in forward_returns.index:
                continue
            fv = factor_values.loc[idx]
            fr = forward_returns.loc[idx]
            ic = self.compute_ic(fv, fr)
            if ic is not None:  # U3/N06: 跳过不可计算的周期（None）
                ic_values.append(ic)
        return pd.Series(ic_values, index=factor_values.index[:len(ic_values)])

    def record(self, symbol: str, factor_code: str, value: float) -> None:
        """Record a factor value for IC tracking.

        Args:
            symbol: Asset symbol/ticker.
            factor_code: Factor identifier.
            value: Computed factor value.
        """
        self._records.append({
            "symbol": symbol,
            "factor_code": factor_code,
            "value": value,
            "timestamp": pd.Timestamp.now(),
        })

    def compute_periodic_ic(
        self,
        factor_values: dict[str, dict[str, float | None]],
        market_data: dict[str, dict[str, Any]],
        window: int = 1,
    ) -> dict[str, float]:
        """Compute single-period IC for each factor code across all symbols.

        Args:
            factor_values: {symbol: {factor_code: value}}
            market_data: {symbol: {close: [float, ...]}}
            window: Forward return window.

        Returns:
            {factor_code: ic_value}
        """
        if not factor_values or not market_data:
            return {}

        symbols = list(factor_values.keys())
        forward_rets = build_forward_returns(market_data, symbols, window)
        if len(forward_rets) < 3:
            return {}

        # Group factor values by code
        factor_by_code: dict[str, dict[str, float]] = {}
        # F3-4 步骤D: 零值占比统计（code -> [zero_count, total_count]）
        _stats: dict[str, list[int]] = {}
        for sym, factors in factor_values.items():
            if not factors:
                continue
            for code, val in factors.items():
                st = _stats.setdefault(code, [0, 0])
                st[1] += 1
                # round14 P2-Z 修复 3: tracking_error 合法值 0.001~0.02——abs<0.001 会把
                # 合法跟踪误差全判零；round35 FS1: 零值口径收敛单点
                # core.factor_values.is_meaningful_value（tracking_error 容差 1e-6，
                # 其余因子默认 0.001，canonical 判定为严格大于）。
                # R58（round28 延伸）: 数据源异常时 factor value 可能为 str，
                # abs(str) → TypeError 使整批 IC 计算失败。非数值视为零分跳过。
                # R58（round28 延伸）: 数据源异常时 factor value 可能为 str，
                # abs(str) → TypeError 使整批 IC 计算失败。非数值视为零分跳过。
                # （isinstance 显式前置供 mypy 窄化；容差判定走 FS1 单点。）
                if not isinstance(val, (int, float)) or not is_meaningful_value(code, val):
                    st[0] += 1
                    continue
                if code not in factor_by_code:
                    factor_by_code[code] = {}
                factor_by_code[code][sym] = val
        self._zero_ratio = {
            c: (st[0] / st[1]) if st[1] else 0.0
            for c, st in _stats.items()
        }

        # P2-9 (round9 §6.5.1-D): IC 口径核对（2026-08-07）——Spearman 秩相关横截面 IC
        # （单期全体标的截面相关），forward return window=1，常量输入/样本<3 返回 None
        # （不写 0 防污染批次）——口径本身正确。vol_ratio IC=0.001 属真实弱因子（ETF 同质化
        # + 量比差异小），非方法缺陷；按 P1-3 已标 warn（|IC|<阈值），待样本累积后按 O6
        # 淘汰线决策，不因弱 IC 修改计算方法。

        # Compute IC per factor code
        ic_results: dict[str, float] = {}
        for code, values in factor_by_code.items():
            fv = pd.Series(values)
            common = fv.index.intersection(forward_rets.index)
            if len(common) < 3:
                # U3/N06: 样本不足跳过该因子（不写 0.0——全 0 批次会覆盖有效 IC）
                continue
            ic_val = self.compute_ic(
                fv[common], forward_rets[common]
            )
            if ic_val is None:
                # U3/N06: 常量输入/NaN → 跳过，不污染批次
                continue
            ic_results[code] = ic_val

        return ic_results

    def compute_icir(self, ic_series: pd.Series) -> float:
        """Compute ICIR = mean(IC) / std(IC).

        Higher values indicate more consistent factor performance.
        """
        if len(ic_series) < 2:
            return 0.0
        std = ic_series.std()
        if std == 0:
            return float('inf')
        return float(ic_series.mean() / std)

    async def save_ic_batch_to_db(self, session: AsyncSession, ic_batch: dict[str, float],
                                  trade_date=None) -> int:
        """Persist the current IC batch to the database（F25① 日频 upsert）。

        F25① (round23 §8): 存储粒度改为「日频 1 行/因子」——(factor_code, trade_date)
        唯一，同一天多次刷新只 upsert 覆盖、不追加。旧实现每 120s 刷新存 1 行
        （4306 行/18 天 ≈240× 虚高 sample_count），被 MIN_IC_SAMPLES=30 在开机 1h
        内全部跨过 →「有效 16」无统计含义。

        F25③/F30: 近零 IC（abs<0.0001）不再丢弃——标记 signal_absent=True 仍落库
        （IC 记 0），修复生存者偏差（旧 `continue` 使落库序列系统性高估 |IC|）。

        Args:
            session: SQLAlchemy async session
            ic_batch: {factor_code: ic_value} dict from registry._last_ic_batch
            trade_date: 交易日（默认北京时间当天；测试可注入固定日期）

        Returns:
            Number of records upserted
        """
        from ..models.factor_ic import FactorICRecord  # lazy import to avoid circular dependency

        if not ic_batch:
            return 0
        trade_date = trade_date or _beijing_today()
        now = datetime.now(timezone.utc)
        count = 0
        for code, ic_val in ic_batch.items():
            # U3/N06: 过滤 None / NaN（常量输入/不可计算）——signal_absent 只标近零，
            # 不标「不可计算」（那类本就无 IC 语义，不占日频行）
            if ic_val is None:
                continue
            if isinstance(ic_val, float) and (ic_val != ic_val):  # NaN 自比较
                continue
            # R58（round28 延伸）: 防御非数值（数据源异常时 factor 可能为 str）
            if not isinstance(ic_val, (int, float)):
                continue
            signal_absent = abs(ic_val) < 0.0001
            stored_ic = 0.0 if signal_absent else round(float(ic_val), 4)
            stmt = sqlite_insert(FactorICRecord).values(
                factor_code=code,
                ic_value=stored_ic,
                ic_ir=0.0,
                signal_absent=signal_absent,
                computed_at=now,
                trade_date=trade_date,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["factor_code", "trade_date"],
                set_={
                    "ic_value": stored_ic,
                    "signal_absent": signal_absent,
                    "computed_at": now,
                },
            )
            await session.execute(stmt)
            count += 1

        # F25①: sample_count 语义 = count(distinct trade_date)（累计交易日数）
        for code in ic_batch:
            sc = await self._get_ic_sample_count_db(session, code)
            await session.execute(
                update(FactorICRecord)
                .where(
                    FactorICRecord.factor_code == code,
                    FactorICRecord.trade_date == trade_date,
                )
                .values(sample_count=sc)
            )

        await session.commit()
        return count

    async def count_distinct_trade_dates(self, session: AsyncSession) -> int:
        """R55 (round27): 当前 factor_ic_records 中 distinct trade_date 总数。

        用于判断是否需要历史回填（已回填则跳过，避免重复）。0 表示从未计算 IC。
        """
        from ..models.factor_ic import FactorICRecord  # lazy import 防循环依赖

        try:
            stmt = select(func.count(func.distinct(FactorICRecord.trade_date)))
            total = (await session.execute(stmt)).scalar_one_or_none() or 0
            return int(total)
        except Exception as e:  # noqa: BLE001 - DB 不可用时回退 0
            logger.warning("[ic_tracker] count distinct trade_date failed: %s", e)
            return 0

    async def get_sample_counts_by_code(self, session: AsyncSession) -> dict[str, int]:
        """R104 (round34): 全因子 IC 累计交易日数一次查询（单一事实源）。

        F25① sample_count 语义 = count(distinct trade_date)（日频 1 行/因子）。
        routers/factors 的 `_db_ic_sample_counts`（/factors/active 路径）与设计
        fdq.ic_accumulation（strategy_design 路径）共用本查询——修复「同一业务量
        多路径不同源」（R94/R95/R104 同族根因）：fdq 曾读 registry 内存
        `_sample_counts`（compute 截面计数 ≤池规模），与 DB 口径分裂 30×+。

        查询失败不在此兜底（抛给调用方决定回退策略：router 回退空 dict、
        strategy_design 回退内存计数）。
        """
        from ..models.factor_ic import FactorICRecord  # lazy import 防循环依赖

        stmt = select(
            FactorICRecord.factor_code,
            func.count(func.distinct(FactorICRecord.trade_date)),
        ).group_by(FactorICRecord.factor_code)
        rows = (await session.execute(stmt)).all()
        return {r[0]: int(r[1]) for r in rows}

    @staticmethod
    def _slice_market_data_day(kline: dict[str, dict[str, Any]], i: int, window: int = 60) -> dict[str, dict[str, Any]]:
        """R55: 从列式 K 线缓存截取「截至第 i 个交易日」的截面 K 线。

        约定与实时 compute 一致——`_kline_cache` 的 close 为**时序升序（旧→新）**
        （`_rows_to_columns` 取 `rows[-days:]` 后仍升序），故 `close[i]` 即第 i 日、
        `close[i-1]` 为前一日；`compute_periodic_ic` 内部 `build_forward_returns` 据此
        计算第 i 日的截面 IC（与实时 IC 同一统计口径，仅时光回溯到历史日）。

        Args:
            kline: {symbol: {"close":[c0..cN-1] 升序, "dates":[d0..dN-1], 可选 open/high/...}}
            i: 目标交易日索引（0=最早，N-1=最新）
            window: 因子计算所需回溯窗口（默认 60，覆盖慢变量因子）

        Returns:
            {symbol: {"close":[...], ...}} 时序升序切片（同 _kline_cache 取向）
        """
        md: dict[str, dict[str, Any]] = {}
        for sym, kd in kline.items():
            if not isinstance(kd, dict):
                continue
            close = kd.get("close")
            if not close or i >= len(close):
                continue
            start = max(0, i - window + 1)
            if len(close[start:i + 1]) < 2:
                # 前 1 日不足以算前收益率，跳过
                continue
            cols: dict[str, Any] = {}
            for key in ("close", "open", "high", "low", "volume", "change_pct"):
                arr = kd.get(key)
                if arr and len(arr) >= i + 1:
                    cols[key] = list(arr[start:i + 1])
            if "close" not in cols:
                continue
            md[sym] = cols
        return md

    async def backfill_ic_history(
        self,
        session: AsyncSession,
        kline: dict[str, dict[str, Any]],
        factor_scores_by_index: dict[int, dict[str, dict[str, float | None]]],
        max_days: int = 400,
    ) -> int:
        """R55 (round27): 一次性批量回填历史截面 IC（非请求驱动，startup-once）。

        根因：IC 由 `_ic_persistence_loop` 增量计算（`save_ic_batch_to_db` 用
        `_beijing_today()` 打当天日期），fresh 库仅 3 个 distinct trade_date → 27 因子
        恒 no_data。本方法复用 K 线缓存，对每个历史交易日 T（kline 索引 i）用「截至 T 的
        因子分」(`factor_scores_by_index[i]`) 计算截面 IC，按 `trade_date=dates[i]` 落库，
        使 distinct trade_date 跳升至 N（回填后先到「可观察」，自然积累 ~11 交易日到
        「有效」，符合用户「接受等自然积累」决策）。

        设计要点：
        - 复用现有 `compute_periodic_ic` / `save_ic_batch_to_db`，口径与实时 IC 完全一致；
        - `MIN_TRADING_DAYS` 门槛**不变**（诚实：不谎报 valid，自然积累到 250 才翻绿）；
        - 一次性批量计算，**无请求路径 IO**（不触网、不依赖 HTTP 请求）；
        - `factor_scores_by_index` 由调用方注入（生产=时光回溯重放 K 线算因子分；
          测试=直接注入历史因子分）。

        Args:
            session: AsyncSession
            kline: {symbol: {"close":[升序], "dates":[升序]}} K 线缓存
            factor_scores_by_index: {i: {symbol: {factor_code: value}}} 截至第 i 日因子分
            max_days: 最多回填天数（防极端长序列）

        Returns:
            实际回填交易日数（≥0）
        """
        if not kline or not factor_scores_by_index:
            return 0
        n = max((len(kd.get("close", [])) for kd in kline.values() if isinstance(kd, dict)), default=0)
        if n < 2:
            return 0
        # 取任一含 dates 的 symbol 作为日期基准
        dates_ref = next((kd["dates"] for kd in kline.values()
                          if isinstance(kd, dict) and kd.get("dates")), None)

        processed = 0
        for i in range(1, min(n, max_days) + 1):
            scores = factor_scores_by_index.get(i)
            if not scores:
                continue
            md = self._slice_market_data_day(kline, i)
            if len(md) < 3:
                # 截面标的不足 3 只 → compute_periodic_ic 不产生 IC，跳过该日
                continue
            try:
                ic_batch = self.compute_periodic_ic(scores, md, window=1)
            except (Exception, asyncio.CancelledError) as exc:
                logger.debug("[ic_backfill] compute_periodic_ic failed at %d: %s", i, exc)
                ic_batch = {}
            if not ic_batch:
                # 历史回填只写有 IC 的日子；全空（常量/样本不足）跳过
                continue
            trade_date = None
            if dates_ref and len(dates_ref) > i:
                trade_date = dates_ref[i]
            if trade_date is None:
                continue
            # SQLite DATE 列接受 date 或 ISO 字符串；统一规整为 date
            if isinstance(trade_date, str):
                try:
                    trade_date = datetime.strptime(trade_date[:10], "%Y-%m-%d").date()
                except ValueError:
                    continue
            try:
                await self.save_ic_batch_to_db(session, ic_batch, trade_date=trade_date)
                processed += 1
            except Exception as exc:
                logger.warning("[ic_backfill] save failed for %s: %s", trade_date, exc)
        return processed

    async def _get_ic_sample_count_db(self, session: AsyncSession, factor_code: str) -> int:
        """P0-12 (round16 3.13 R2/R3): 样本数统计「IC 累积周期数」。

        F25① (round23): 周期数语义修正——由 `count(*)`（刷新次数，240× 虚高）改为
        `count(distinct trade_date)`（日频交易日数，1 天 1 期）。合理值现 ≈运行天数，
        随运行增长；`MIN_TRADING_DAYS=250` 为有效门槛（对齐业内 t≥2 所需样本量）。
        """
        from ..models.factor_ic import FactorICRecord  # lazy import 防循环依赖

        try:
            stmt = select(func.count(func.distinct(FactorICRecord.trade_date))).select_from(
                FactorICRecord
            ).where(FactorICRecord.factor_code == factor_code)
            total = (await session.execute(stmt)).scalar_one_or_none() or 0
            return int(total)
        except Exception as e:  # noqa: BLE001 - DB 不可用时回退内存计数
            logger.warning("[ic_tracker] DB sample count failed (fallback memory): %s", e)
            return self._get_ic_sample_count(factor_code)

    def _get_ic_sample_count(self, factor_code: str) -> int:
        """Count occurrences of *factor_code* in internal records（内存语义，兼容旧调用）。"""
        return sum(
            1 for r in self._records
            if isinstance(r, dict) and r.get("factor_code") == factor_code
        )


# Global singleton
ic_tracker = ICTracker()
