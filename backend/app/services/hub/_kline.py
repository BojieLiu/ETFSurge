"""K-line / history cache mixin — split from market_data_hub (Batch 3)."""

import asyncio
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

class KlineMixin:
    _KLINE_CACHE_PERSIST_PATH: str | None = None


    _KLINE_CACHE_TTL: float = 86400.0  # 24h


    _kline_stale_flags: dict[str, bool] = {}


    _WIDE_BASIS_INDEX_CODES = {
        "510300": "sh000300",  # 沪深300
        "159919": "sh000300",  # 沪深300（深市嘉实）
        "510500": "sh000905",  # 中证500
        "159922": "sh000905",  # 中证500（深市）
        "510050": "sh000016",  # 上证50
        "588000": "sh000688",  # 科创50
        "159915": "sz399006",  # 创业板指
        "510880": "sh000015",  # 上证红利
        "159338": "sh000510",  # 中证A500（O19；round9 P0-8: 560600 → 159338）
        "563080": "sh932000",  # 中证A50（O19）
        "562000": "sh000903",  # 中证A100（O19）
        "563020": "sh000922",  # 红利低波（O19，中证红利低波动指数）
        "512890": "sh000922",  # 红利低波ETF（O19，同指数）
        "510180": "sh000010",  # 上证180（O19）
        "159901": "sz399001",  # 深证100（O19）
        "159800": "sh000906",  # 中证800（O19）
        "159845": "sh000852",  # 中证1000（O19）
        # FM3 探针 B（round35 §15.5）补充：512100 南方中证1000ETF 与 159845 同指
        # 数——搜索链路名称实证「中证1000ETF南方」（2026-08-24），消除探针样本中
        # 唯一可补的映射缺口（518880 商品无基准，维持宁缺毋滥不映射）。
        "512100": "sh000852",  # 中证1000ETF（南方）→ 中证1000
        "159601": "sh932000",  # 中国A50ETF（O19，同 A50 指数）
        # P1-8 (round9 §6.5.1-B): 主题 ETF 基准映射扩展——行业/主题 ETF 此前无基准映射
        # → benchmark_close 全缺 → tracking_error no_data。仅收录实测（2026-08-07 腾讯行情
        # 200 且名称非空）确认的指数代码；未确认的（半导体/新能源车等）宁缺毋滥
        # （错误基准比缺失更误导，见 P2-10 幽灵锚教训）。
        "512880": "sz399975",  # 证券ETF → 中证全指证券公司（实测）
        "512010": "sh000933",  # 医药ETF → 中证医药（实测）
        # P1-J (round10 §5.5/§10): benchmark_close 映射扩到候选池主要行业/主题
        # ETF（东财/腾讯行情实测 2026-08-09 名称匹配 + 指数对应，消除 tracking_error
        # 0 命中）。未收录仍保持「宁缺毋滥」——只加能确认对应的。
        "512690": "sh000932",  # 酒ETF → 中证白酒
        "512170": "sh000933",  # 医疗ETF → 中证医疗（同医药基准）
        "512760": "sh000733",  # 芯片ETF → 中华半导体芯片
        "159995": "sz399812",  # 芯片ETF → 国证半导体芯片
        "512480": "sh931071",  # 半导体ETF → 中证全指半导体
        "515790": "sh930997",  # 光伏ETF → 中证光伏产业
        "515030": "sh930714",  # 新能源汽车ETF → 中证新能源汽车
        "516160": "sh931151",  # 新能源ETF → 中证新能源
        "512400": "sh000819",  # 有色金属ETF → 中证有色金属
        "512800": "sh000806",  # 银行ETF → 中证银行
        "512000": "sh930791",  # 券商ETF → 中证全指证券公司（沪市）
        "159920": "sz399933",  # 恒生ETF（港）→ 恒生指数
        "513050": "sh000856",  # 中概互联ETF → 中证海外中国互联网
    }


    _FUND_SHARES_CACHE: dict[str, tuple[float, dict]] = {}


    _FUND_SHARES_TTL = 86400.0


    _ENRICH_TOTAL_TIMEOUT = 60.0


    @staticmethod
    def _rows_to_columns(rows: list[dict], days: int = 60) -> dict[str, list[float]]:
        """R3: 将行式 K 线数据转为列式（懒转换）。

        Input:  [{date, open, high, low, close, volume}, ...]
        Output: {close: [3.45, ...], high: [3.5, ...], low: [3.3, ...], volume: [1e7, ...],
                 change_pct: [0.5, ...]}
        """
        if not rows:
            return {"close": [], "high": [], "low": [], "volume": [], "change_pct": []}
        tail = rows[-days:]
        closes = [r.get("close", r.get("close", 0)) for r in tail]
        highs = [r.get("high", r.get("high", r.get("close", 0))) for r in tail]
        lows = [r.get("low", r.get("low", r.get("close", 0))) for r in tail]
        vols = [r.get("volume", r.get("volume", 0)) for r in tail]

        change_pct = [0.0]
        for i in range(1, len(closes)):
            if closes[i - 1]:
                change_pct.append(round((closes[i] - closes[i - 1]) / closes[i - 1] * 100, 2))
            else:
                change_pct.append(0.0)

        return {
            "close": closes,
            "high": highs,
            "low": lows,
            "volume": vols,
            "change_pct": change_pct,
        }


    def _kline_cache_path(self) -> str:
        """磁盘缓存文件路径（data/kline_cache.json，R86 修正为挂载卷 data_dir）。"""
        if self._KLINE_CACHE_PERSIST_PATH:
            return self._KLINE_CACHE_PERSIST_PATH
        try:
            from ...config import settings
            _data_dir = getattr(settings, "data_dir", None)
            if not _data_dir:
                # R86 (round30): Settings.data_dir 属性缺失 → 退回旧 fallback（源码目录），
                # 必须 WARNING——容器内写到非挂载卷意味着重启即丢（R86 根因）。
                _data_dir = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
                )
                logger.warning(
                    "[hub] settings.data_dir missing — kline cache falls back to %s "
                    "(container restart will lose it, R86)",
                    _data_dir,
                )
        except Exception:
            _data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data"
            )
        self._KLINE_CACHE_PERSIST_PATH = os.path.join(_data_dir, "kline_cache.json")
        return self._KLINE_CACHE_PERSIST_PATH


    def _load_kline_cache_sync(self) -> None:
        """启动加载磁盘 K 线缓存（24h 内复用；过期/缺失/损坏 → 静默空，诚实重建）。

        仅填充行式缓存 + 时间戳；列式缓存由 _sync_columnar_cache 懒重建（避免
        __init__ 阶段重复计算——refresh_kline/首个 get_kline 都会触发）。
        """
        import json as _json
        import time as _t
        try:
            _path = self._kline_cache_path()
            if not os.path.isfile(_path):
                return
            _mtime = os.path.getmtime(_path)
            if _t.time() - _mtime > self._KLINE_CACHE_TTL:
                logger.info("[hub] kline cache on disk %.1fh old — expired, rebuilding (R59③)",
                            (_t.time() - _mtime) / 3600.0)
                return
            with open(_path, "r", encoding="utf-8") as f:
                _data = _json.load(f)
            if not isinstance(_data, dict):
                return
            _rows = _data.get("rows")
            _ts = float(_data.get("ts") or 0.0)
            _syms = _data.get("symbols") or []
            if not isinstance(_rows, dict) or not _rows:
                return
            self._kline_cache_rows = {str(k): v for k, v in _rows.items()
                                      if isinstance(v, list) and v}
            self._kline_cache_ts = _ts
            self._kline_cache_symbols = [str(s) for s in _syms]
            if self._kline_cache_rows:
                # 列式缓存同步重建（get_kline 旧调用方兼容）
                try:
                    self._sync_columnar_cache()
                except Exception:
                    pass
                logger.info(
                    "[hub] kline cache loaded from disk: %d symbols (age=%.1fh, R59③)",
                    len(self._kline_cache_rows), (_t.time() - _ts) / 3600.0,
                )
        except Exception as _e:
            logger.debug("[hub] kline cache load failed (non-fatal): %s", _e)


    def _persist_kline_cache_sync(self) -> None:
        """落盘 K 线缓存（refresh_kline 更新后调用；失败静默，不影响主流程）。"""
        import json as _json
        try:
            if not self._kline_cache_rows:
                return
            _path = self._kline_cache_path()
            _tmp = f"{_path}.tmp"
            with open(_tmp, "w", encoding="utf-8") as f:
                _json.dump({
                    "rows": self._kline_cache_rows,
                    "ts": self._kline_cache_ts,
                    "symbols": self._kline_cache_symbols,
                }, f, ensure_ascii=False)
            os.replace(_tmp, _path)
        except Exception as _e:
            logger.debug("[hub] kline cache persist failed (non-fatal): %s", _e)


    async def flush_kline_cache(self) -> None:
        """round35 §12-P0-3: 关停前落盘 K 线缓存（lifespan shutdown 调用）。

        此前 main.py 关停段以 ``getattr(hub, "flush_kline_cache", None)`` 防御性
        调用，但本方法不存在 → 永久静默 no-op（假完成）。落盘走线程池（JSON 可达
        MB 级，勿阻塞事件循环）；失败静默——与 _persist_kline_cache_sync 同语义，
        关停路径不因缓存落盘失败而中断。
        """
        try:
            from ...core.async_utils import run_sync

            await run_sync(self._persist_kline_cache_sync, timeout=15)
            if self._kline_cache_rows:
                logger.info("[hub] kline cache flushed on shutdown (%d symbols)",
                            len(self._kline_cache_rows))
        except Exception as _e:
            logger.debug("[hub] kline flush on shutdown failed (non-fatal): %s", _e)

    def get_kline(self, symbol: str, max_age: int = 300) -> dict[str, Any] | None:
        """R3: 从行式缓存懒转换返回列式 K 线数据。

        Args:
            symbol: ETF 代码。
            max_age: 缓存最大时效（秒），默认 300s（5 分钟）。

        Returns:
            列式 K 线数据 {close:[], high:[], ...}，或 None。
        """
        rows = self.get_kline_rows(symbol, max_age=max_age)
        if rows is None or not rows:
            return None
        return self._rows_to_columns(rows)


    def get_kline_symbols(self) -> list[str]:
        """返回缓存中有 K 线数据的 ETF 代码列表。"""
        return list(self._kline_cache_rows.keys())


    def get_history(self, symbol: str, market: str = "A", period: str = "daily") -> list[dict] | None:
        """实时取历史 K 线（委托 china_market.fetch_history，含 fallback 链）。"""
        try:
            from ...fetchers.china_market import fetch_history
            return fetch_history(symbol, market, period) or []
        except Exception as e:
            logger.warning("[hub] get_history(%s) failed: %s", symbol, e)
            return None


    def get_kline_rows(self, symbol: str, max_age: int = 300) -> list[dict] | None:
        """R3: 获取行式 K 线数据（直接读缓存，无转换）。

        Args:
            symbol: ETF 代码。
            max_age: 缓存最大时效（秒）。

        Returns:
            行式 K 线 [{date, open, high, low, close, volume}, ...]，或 None。
        """
        rows = self._kline_cache_rows.get(symbol)
        if rows and (time.time() - self._kline_cache_ts) < max_age:
            return rows
        return None


    def get_kline_rows_any(self, symbol: str) -> list[dict] | None:
        """F0-4: 返回任意年龄的 K 线缓存（不检查新鲜度）。"""
        return self._kline_cache_rows.get(symbol) or None


    def get_kline_age_seconds(self, symbol: str) -> float | None:
        """F0-4: 缓存数据龄（秒），无缓存返回 None。"""
        if symbol in self._kline_cache_rows:
            return max(0.0, time.time() - self._kline_cache_ts)
        return None


    def mark_kline_stale(self, symbol: str, stale: bool = True) -> None:
        """F0-4: 记录该 symbol 最近一次 history 是否走了 stale 兜底。"""
        self._kline_stale_flags[symbol] = stale


    def is_kline_stale(self, symbol: str) -> bool:
        """F0-4: 查询该 symbol 是否最近一次 history 走了 stale 兜底。"""
        return self._kline_stale_flags.get(symbol, False)


    async def refresh_kline(self, symbols: list[str]) -> None:
        """S5: 增量刷新 K 线缓存（R3: 直接 fetch_history + Semaphore 并发）。

        不再经过 factor_registry._fetch_market_data（消除循环依赖）。
        统一存储行式格式，get_kline() 时懒转换为列式。

        Args:
            symbols: 需要刷新的 ETF 代码列表。
        """
        if not symbols:
            return
        from ...core import async_utils
        from ...fetchers import china_market

        sem = asyncio.Semaphore(5)  # R3: 并发控制

        async def _fetch_one(sym: str) -> tuple[str, list[dict] | None]:
            async with sem:
                try:
                    # R68 (round29): 走 long 池——默认池被 watchlist/design 打满时
                    # refresh_kline 会被饿死（round29 §14.4.0 池饱和实证），
                    # 冷缓存永不建立 → 四路下游级联失效。
                    rows = await async_utils.run_sync_long(
                        china_market.fetch_history, sym, "A", "daily", timeout=20
                    )
                    return sym, rows
                except Exception as e:
                    logger.debug("[pool] refresh_kline fetch_history(%s) failed: %s", sym, e)
                    return sym, None

        tasks = [_fetch_one(sym) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        async with self._kline_cache_lock:
            updated = 0
            for r in results:
                if isinstance(r, tuple) and len(r) == 2:
                    sym, rows = r
                    if isinstance(rows, list) and rows:
                        self._kline_cache_rows[sym] = rows
                        self.mark_kline_stale(sym, False)
                        updated += 1
                    else:
                        # R68 (round29): 失败/空 → 保留 last-good 旧值并标 stale，
                        # 不清空（旧值可用比无数据强，且消费方能看到 stale 标记）。
                        if self._kline_cache_rows.get(sym):
                            self.mark_kline_stale(sym, True)
                            logger.debug(
                                "[pool] refresh_kline(%s) failed — keeping last-good rows (R68)", sym
                            )
            if updated > 0:
                self._kline_cache_ts = __import__('time').time()
                self._kline_cache_symbols = list(set(self._kline_cache_symbols + symbols))
                # 同步更新列式缓存（向后兼容 get_kline 旧调用方）
                self._sync_columnar_cache()
                logger.debug("[pool] refresh_kline updated %d/%d symbols", updated, len(symbols))
            # R59③ (round28): 更新后落盘——重启后首呼 design 直接加载磁盘缓存，
            # 消除 42-75s 冷建库（round28 §14.4 冷启动超时根因）。失败静默。
            # R68 (round29): 落盘条件从 `updated > 0` 放宽到「缓存非空」——全失败
            # 轮次也刷新磁盘 mtime，否则 _load_kline_cache_sync 的 24h TTL 会把
            # 仍然可用的旧缓存判过期丢弃（冷启动循环放大，§14.4.1 ①）。
            # 落盘频率提高后改走线程池（JSON 可达 MB 级，勿阻塞事件循环）。
            if self._kline_cache_rows:
                try:
                    await async_utils.run_sync(self._persist_kline_cache_sync, timeout=15)
                except Exception as _pe:
                    logger.debug("[hub] kline persist submit failed (non-fatal): %s", _pe)


    def _sync_columnar_cache(self):
        """R3: 从行式缓存重建列式缓存（兼容旧 get_kline 调用方）。"""
        self._kline_cache = {}
        for sym, rows in self._kline_cache_rows.items():
            cols = self._rows_to_columns(rows)
            if cols and cols.get("close"):
                self._kline_cache[sym] = cols


    def _build_symbol_extra(self, symbols: list[str]) -> dict[str, dict]:
        """构建 symbol_extra 字典，供 factor_registry 使用。"""
        result = {}
        for sym in symbols:
            entry = self._by_code.get(sym, {})
            result[sym] = {
                "fund_scale": entry.get("fund_scale", 0),
                "fund_shares": entry.get("fund_shares", 0),
                # F19: carry industry/concepts for china_specific factors
                "industry": entry.get("industry", "unknown"),
                "concepts": entry.get("concepts", []),
            }
        return result


    async def _enrich_symbol_extra(
        self,
        symbols: list[str],
        base_extra: dict[str, dict],
    ) -> dict[str, dict]:
        """F3-4 步骤B/C: 注入 benchmark_close（宽基指数历史 close）与 shares_change_20d（份额变化）。

        - benchmark_close → tracking_error（§9.5.4 步骤B，宽基先行）
        - shares_change_20d → shares_change 直接生效 + institutional_holdings_change ×0.5 折扣代理
        - 任一失败静默（不阻塞主流程），份额数据 24h 缓存
        """
        from ...fetchers.china_market import fetch_etf_shares_outstanding

        out = {s: dict(base_extra.get(s) or {}) for s in symbols}

        # P2-1 延伸 (R4-16): 并发限制 + 总超时——66 只 × 2 个任务无限制并发
        # 会在 NAV/份额数据源慢时打满线程池（POOL SATURATION，get_fund_nav 6s 超时
        # × 大量堆积）→ 候选池刷新永远失败 → verify_e2e 候选池类检查全 FAIL。
        # Semaphore(8) 控制并发 + wait_for 总超时（超时降级为部分数据，不阻塞刷新）。
        _sem = asyncio.Semaphore(8)

        async def _bench(sym: str):
            async with _sem:
                idx_code = self._WIDE_BASIS_INDEX_CODES.get(sym)
                if not idx_code:
                    return
                try:
                    hist = await self.get_market_history(idx_code, "index", "daily")
                    # FM3 探针修复（round35 §15.5）：行键双方言容错——fetchers 层
                    # 「系统格式」是中文键（日期/收盘/...，akshare 主源路径），但
                    # BaoStock/Tencent 分支可能给英文键。此前只读英文键 "close"，
                    # akshare 源胜出时 closes 恒空 → benchmark_close 静默饿死、
                    # tracking_error no_data。对齐 market_service T-1 兜底的
                    # `close or 收盘` 双读模式。
                    closes = []
                    for r in (hist or []):
                        c = r.get("close") or r.get("收盘")
                        if c:
                            try:
                                closes.append(float(c))
                            except (TypeError, ValueError):
                                continue
                    if len(closes) >= 5:
                        out.setdefault(sym, {})["benchmark_close"] = closes[-20:]
                except Exception as e:
                    logger.debug("[hub] benchmark_close for %s failed: %s", sym, e)

        async def _shares(sym: str):
            async with _sem:
                try:
                    cached = self._FUND_SHARES_CACHE.get(sym)
                    if cached and (time.time() - cached[0]) < self._FUND_SHARES_TTL:
                        shares_data = cached[1]
                        _have_change = shares_data is not None and shares_data.get("shares_change_20d") is not None
                    else:
                        from ...core.async_utils import run_sync
                        # R147-FIX: 优先交易所官方份额源（SSE/SZSE，免费无认证），可算
                        # 20 日变化率；失败回退旧 EM 源（仅当前份额，change_20d=None）。
                        from ...fetchers.fund_share_fetcher import fetch_share_change_20d
                        shares_data = await run_sync(fetch_share_change_20d, sym, timeout=10)
                        _have_change = shares_data is not None and shares_data.get("shares_change_20d") is not None
                        if not _have_change:
                            # 回退旧源（EM spot 当前份额；change_20d 可能仍 None）
                            shares_data = await run_sync(fetch_etf_shares_outstanding, sym, timeout=10)
                            _have_change = shares_data is not None and shares_data.get("shares_change_20d") is not None
                        # F19 R71: 失败/空结果不写 24h 成功缓存——旧代码 `or {}` 把失败变成
                        # {} 写进缓存 → 后续 24h 命中 {} → gap 持续；akshare 恢复后还要再等
                        # 24h 才重试（熔断恢复后自动补齐被缓存破绽阻断）
                        if not shares_data or not _have_change:
                            return
                        self._FUND_SHARES_CACHE[sym] = (time.time(), shares_data)
                    if shares_data.get("shares_change_20d") is not None:
                        out.setdefault(sym, {})["shares_change_20d"] = shares_data["shares_change_20d"]
                        # §9.10.7-5 确认: institutional_holdings_change 用 ×0.5 折扣代理
                        out[sym]["institutional_holdings_change"] = float(shares_data["shares_change_20d"]) * 0.5
                except Exception as e:
                    logger.debug("[hub] shares_change_20d for %s failed: %s", sym, e)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_bench(s) for s in symbols),
                    *(_shares(s) for s in symbols),
                ),
                timeout=self._ENRICH_TOTAL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[hub] symbol_extra enrich timed out after %ss (partial: %d/%d symbols)",
                self._ENRICH_TOTAL_TIMEOUT, len(out), len(symbols),
            )
        return out
