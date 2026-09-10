"""startup — warmup 计时/分段/预算告警纯函数（P2-3, docs/redundant-review.md §3 D6）。

冗余评审 D6 判定: main.py 1058+ 行 lifespan 聚合过多——warmup 计时/分段标签与
业务启动逻辑混排。本模块把「可单测的纯函数段」从 main.py 迁出：

- ``_WARMUP_SEQUENCE_LABELS`` / ``_WARMUP_SEGMENTS`` / ``_record_warmup_segment``
- ``_warmup_uncovered_segments`` / ``_format_warmup_budget_warning``
- ``_run_warmup_sequence``（串行编排，纯异步无 I/O 常量）

⚠️ main.py 保留同名 re-export（``from .tasks.startup import *`` 式显式清单）——
既有测试（test_warmup_sequence/test_warmup_two_phase 等）从 ``app.main`` 导入
这些符号，源码级守卫 ``main_mod.__file__`` 仍指向 main.py。后续批次再迁移
lifespan 内的 ``_warmup_*`` 协程族（需连带迁移 app.state 钩子，行为风险更高）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Generator

logger = logging.getLogger(__name__)


def _warmup_timer():
    """惰性解析 main 的 warmup_timer（PROFILE_WARMUP 动态装配，避免循环 import）。"""
    from ..main import warmup_timer
    return warmup_timer

# R170 (round52): sequence 7 段标签——budget 告警与 warmup_timing.json 同口径。
_WARMUP_SEQUENCE_LABELS: tuple[str, ...] = (
    "market_cache",
    "etf_cache",
    "global_indices",
    "sector_cache",
    "instruments_sync",
    "indices_meta_sync",
    "design_data",
)

_WARMUP_SEGMENTS: list[dict[str, object]] = []


def _record_warmup_segment(label: str, duration_s: float) -> None:
    """记录一个预热 sequence 分段的实测耗时（供 budget 告警归因）。"""
    _WARMUP_SEGMENTS.append({"label": label, "duration_ms": round(duration_s * 1000.0, 2)})


def _warmup_uncovered_segments(
    expected: tuple[str, ...] | list[str] | None = None,
) -> list[str]:
    """返回「在 sequence 中但未留下分段计时」的段名（归属缺口自曝）。"""
    _expected = tuple(expected) if expected is not None else _WARMUP_SEQUENCE_LABELS
    _covered = {str(s["label"]) for s in _WARMUP_SEGMENTS}
    return [lb for lb in _expected if lb not in _covered]


def _format_warmup_budget_warning(
    elapsed: float,
    budget: float,
    segments: list[dict[str, object]],
    uncovered: list[str],
) -> str:
    """生成带归因信息的预热预算日志文案（纯函数，可单测）。"""
    def _ms(s: dict[str, object]) -> float:
        v = s.get("duration_ms")
        return float(v) if isinstance(v, (int, float)) else 0.0

    _top = sorted(segments, key=_ms, reverse=True)[:3]
    _parts: list[str] = []
    if _top:
        _parts.append(
            "分段 top3: "
            + "/".join(f"{s.get('label', '?')} {_ms(s) / 1000.0:.1f}s" for s in _top)
        )
    if uncovered:
        _parts.append("未入 timing 段: " + ",".join(uncovered))
    _attr = f"（{'; '.join(_parts)}）" if _parts else "（无分段计时数据）"
    if elapsed > budget:
        return (
            f"[warmup-budget] 预热总耗时 {elapsed:.1f}s 超过预算阈值 {budget:.1f}s，"
            f"可能存在回归{_attr}——见 logs/warmup_timing.json（PROFILE_WARMUP=1）"
        )
    return f"[warmup-budget] 预热总耗时 {elapsed:.1f}s（阈值 {budget:.1f}s，达标）"


async def _run_warmup_sequence(tasks: list) -> None:
    """O2 (round7 §7 P2): 预热任务串行执行——控并发峰值。

    旧实现 4 个重 IO 预热任务同时 create_task，各自内部并发 run_sync + 全量
    扫描 + akshare 分页叠加 → 预热高峰 shared_executor 64/64 饱和（P2 复现）。
    串行执行（前一个完成后启动下一个），内部并发上限不变；单个任务异常
    不阻断后续任务（预热失败静默，启动不阻塞）。

    R170 (round52): tasks 元素可为裸协程（向后兼容）或 ``(label, coro)``；带 label
    时记录分段耗时（无论任务成功/失败/超时——失败段同样要可归因）。
    """
    for _item in tasks:
        _label, _t = _item if isinstance(_item, tuple) else ("", _item)
        _t0 = time.time()
        try:
            await _t
        except Exception as e:  # noqa: BLE001
            logger.warning("[lifespan] warmup sequence step failed (non-fatal): %s", e)
        finally:
            if _label:
                _record_warmup_segment(_label, time.time() - _t0)


async def _warmup_sector_lists() -> None:
    """预热概念/行业板块全量列表缓存（冷首呼 38.9s → 命中缓存）。

    不占 startup 关键路径（warmup 30s 预算外，§14.6 原则：就绪后后台异步预拉）。
    失败静默（首呼回源兜底）；run_sync_long 走长任务线程池（不阻塞事件循环）。
    """
    try:
        from ..core.async_utils import run_sync_long
        from ..fetchers.sector_fetcher import (
            fetch_concept_sectors,
            fetch_industry_sectors,
        )
        await asyncio.gather(
            run_sync_long(fetch_concept_sectors, 150, timeout=40),
            run_sync_long(fetch_industry_sectors, 80, timeout=40),
            return_exceptions=True,
        )
        logger.info("[warmup] sector list prefetch done (concept/industry, R89)")
    except Exception as _e:
        logger.debug("[warmup] sector list prefetch failed (non-fatal): %s", _e)



# ═══ P2-3 第二批（round53 遗留批）: warmup 协程族 ═════════════════════
# 从 main.py lifespan 内嵌迁移为模块级（参数化 state=app.state）；
# main.py 保留 re-export（测试导入面）+ 装配调用。源码级守卫（R56/R59④ 基数断言）
# 已同步指向本文件。

async def _background_instruments_sync() -> None:
    try:
        from ..services.instruments_sync import sync_instruments_table
        # O1 (round8 §7 P0-新): 整体超时兜底——即使某段 akshare 黑洞，
        # 90s 内必然结束（线程池内继续、事件循环不阻塞），不拖累启动。
        n = await asyncio.wait_for(sync_instruments_table(), timeout=90)
        if n:
            logger.info("[lifespan] instruments table auto-synced: %d rows", n)
    except Exception as e:  # noqa: BLE001
        logger.warning("[lifespan] instruments auto-sync failed (non-fatal): %s", e)

# P0-20 (round16 3.21): indices_meta 表接入启动同步（round14 P2-AG 未落地）——
# 表此前是静态快照无增量机制，"恒生港股通"系列从未进表 → 搜索恒缺。
# 与 instruments 同模式：后台任务 + 超时 + 失败静默（表已有历史数据不覆盖清空）。
async def _background_indices_meta_sync() -> None:
    try:
        from ..services.indices_meta_sync import sync_indices_meta_table
        n = await asyncio.wait_for(sync_indices_meta_table(), timeout=120)
        if n:
            logger.info("[lifespan] indices_meta table auto-synced: %d rows", n)
    except Exception as e:  # noqa: BLE001
        logger.warning("[lifespan] indices_meta auto-sync failed (non-fatal): %s", e)


# 启动时预热行情缓存——F3 (round27): 改后台异步，不再阻塞 startup 就绪。
# 旧实现 `await refresh_market_cache(timeout=10)` 仍占 10s 启动关键路径
# （A 股全市场快照 stock_zh_a_spot 实测 ~24s，10s 超时截断仍拖慢启动）。
# 改为后台填充（与 sector cache 同模式，R44 已验证安全）：startup 不被拖长；
# market cache 缺失时首个请求会触发按需刷新（refresh_market_cache 亦被
# 运行时周期/按需调用），不丢数据。
async def _warmup_market_cache(state) -> None:
    try:
        async def _do_market_warmup():
            _mark = state.warmup["market_cache"]
            # round49 A4 (2e7f680) + A4-C: 拆两阶段预热, 治本 warmup 10.57s
            # 根因 (off_exchange 串行 fetch_fund_nav 拉长整体).
            #   - fast 阶段 (5s timeout): A 股+指数, 写 cache, 用户首击命中
            #   - slow 阶段 (25s timeout): off_exchange 补全, 后台写 cache 覆盖
            # 旧 10s timeout 走 "all" 完整 → 必超时 → 静默失败.
            with _warmup_timer()("warmup_market_cache", "warmup", "行情缓存预热 (两阶段)"):
                try:
                    # fast 阶段: 5s 内拿快源, 写 cache
                    await asyncio.wait_for(
                        refresh_market_cache(phase="fast"),
                        timeout=5,
                    )
                    _mark["done"] = True
                    _mark["success"] = True
                    _mark["phase"] = "fast"
                    logger.info("行情缓存预热 fast 阶段完成 (后台 slow 续传)")
                    # slow 阶段: 后台续传, 不 await 阻塞 startup
                    async def _slow_warmup():
                        try:
                            await asyncio.wait_for(
                                refresh_market_cache(phase="slow"),
                                timeout=25,
                            )
                            logger.info("行情缓存预热 slow 阶段完成")
                        except (Exception, asyncio.CancelledError) as exc:
                            logger.debug("行情缓存预热 slow 阶段失败 (非阻塞): %s", exc)
                    asyncio.create_task(_slow_warmup())
                except (Exception, asyncio.CancelledError) as exc:
                    _mark["done"] = True
                    _mark["success"] = False
                    _mark["phase"] = "fast_failed"
                    logger.debug("行情缓存预热 fast 阶段失败 (非阻塞): %s", exc)

        # 不 await：立即返回让 startup 就绪；实际刷新在后台进行
        task = asyncio.create_task(_do_market_warmup())
        state._market_warmup_task = task  # 强引用防 GC 回收未完成任务
        logger.info("行情缓存预热已在后台启动（非阻塞，F3）")
    except (Exception, asyncio.CancelledError) as exc:
        logger.warning("行情缓存预热任务启动失败（非阻塞）：%s", exc)

# 启动时预热全球指数缓存（非阻塞，15s 超时）
async def _warmup_global_indices(state) -> None:
    with _warmup_timer()("warmup_global_indices", "warmup", "全球指数缓存预热"):
        _mark = state.warmup["global_indices"]
        try:
            # R5-2-3: 缓存命中即跳过（与 R4-26 失败缓存模式一致）——磁盘 last_ok
            # 缓存 24h 内有效时直接复用，不触网（旧逻辑仅 1h 内跳过 → 冷拉 1.09s 热点）。
            # R86 (round30): 落盘到 settings.data_dir（挂载卷），替代 dirname×3 的
            # 源码目录（容器内 `__file__×3` = `/` → `/data/indices_cache.json` 非挂载卷）。
            from app.config import settings as _st

            from ..services.market_service import (
                _GLOBAL_INDICES_OK_TTL,
                _global_indices_last_ok,
                _load_ok_cache,
                get_global_indices,
            )
            # round36 ASYNC240 修复：os.path 元数据探测移入 to_thread（事件循环不阻塞）
            def _probe_ok_cache_mtime() -> float | None:
                # round35 RC-C6: 落点单点收敛至 settings.data_dir——删除 dirname×3
                # fallback（与 market_service.indices_cache 同源漂移，一并收口）。
                _pp = os.path.join(str(getattr(_st, "data_dir", "")), "indices_cache.json")
                return os.path.getmtime(_pp) if os.path.isfile(_pp) else None

            _mtime = await asyncio.to_thread(_probe_ok_cache_mtime)
            _cache_hit = False
            if _mtime is not None:
                _age = time.time() - _mtime
                if _age < _GLOBAL_INDICES_OK_TTL:
                    _load_ok_cache()
                    if _global_indices_last_ok:
                        _cache_hit = True
                        logger.info(
                            "全球指数本地缓存 %.1fs 内有效（24h 缓存命中），跳过网络预热（R5-2-3）",
                            _age,
                        )
                        _mark["done"] = True
                        _mark["success"] = True
                        return
            if not _cache_hit:
                await asyncio.wait_for(get_global_indices(), timeout=15)
                _mark["done"] = True
                _mark["success"] = True
                logger.info("全球指数缓存预热完成（网络拉取）")
        except (Exception, asyncio.CancelledError):
            _mark["done"] = True
            _mark["success"] = False
            logger.exception("全球指数缓存预热失败（非交易时段正常）")
# R56 (round28): 删除独立启动 global_indices 预热 task（旧逻辑残留）——
# _warmup_sequence_task 的 sequence 内已包含 global_indices 预热（:334）。
# 两者并发启动、同时 miss 24h 缓存 → 各自网络拉取 → 预热 18.4s 双重执行回归
# （warmup_timing.json 两条记录）。F3 重构（5b0c2fa）时遗漏删除旧独立 task
# 是「重构遗漏」典型；此处只保留 sequence 调用。

# 启动时预热 ETF 缓存（非阻塞），带超时保护
async def _warmup_etf_cache(state) -> None:
    with _warmup_timer()("warmup_etf_cache", "warmup", "ETF 扫描预热"):
        _mark = state.warmup["etf_cache"]
        try:
            from app.fetchers.etf_scanner import fetch_all_etfs_base

            from ..core.async_utils import run_sync
            result = await run_sync(fetch_all_etfs_base, timeout=120)
            _mark["done"] = True
            _mark["success"] = bool(result)
            if result:
                logger.info("ETF cache warmup done: %d items", len(result))
        except asyncio.TimeoutError:
            _mark["done"] = True
            _mark["success"] = False
            logger.warning("ETF full scan timed out (120s), will complete on demand")
        except Exception as e:
            _mark["done"] = True
            _mark["success"] = False
            logger.warning("ETF cache warmup failed: %s", e)

# O2 (round7 §7 P2): 预热任务串行化——旧实现 4 个重 IO 任务（market_cache /
# etf_cache / global_indices / instruments_sync）同时 create_task，各自内部
# 8 并发 run_sync + 全量扫描 + akshare 分页叠加 → 预热高峰 shared_executor
# 64/64 饱和（round7 P2 复现）。改为一个编排任务按顺序串行执行（前一个
# 完成后启动下一个），内部并发上限不变；每个子任务自带超时/失败隔离。
# round25 R32: 预热覆盖冷拉取路径——板块缓存（sectors/heat + 板块动量 +
# 热点板块）首个请求不再冷拉 4.7s（旧实现 60s 循环首次触发在启动后 ~10s+，
# 首个用户请求仍可能撞冷缓存）。
async def _warmup_sector_cache(state) -> None:
    # R44 (round27): 板块缓存预热改后台异步——不再阻塞 startup 就绪。
    # 旧实现 await refresh_sector_cache()，非交易时段/源冷却时该调用失败
    # （Connection aborted）仍耗 12.8s 空转，拖长整体预热（34.5s 回归）。
    # 改为：启动后台任务填充 sector cache，本函数立即返回，startup 不被拖长；
    # 失败仅 DEBUG/WARNING，不崩溃、不影响其它预热步骤。
    try:
        from .sector_refresh import refresh_sector_cache

        async def _do_sector_warmup():
            try:
                await asyncio.wait_for(refresh_sector_cache(), timeout=15)
                logger.info("板块缓存预热完成（后台）")
            except (Exception, asyncio.CancelledError) as exc:
                logger.debug("板块缓存预热失败（后台，非阻塞）：%s", exc)

        # 不 await：立即返回让 startup 就绪；实际刷新在后台进行
        task = asyncio.create_task(_do_sector_warmup())
        # 持有强引用防止事件循环 GC 回收未完成的后台任务
        state._sector_warmup_task = task
        logger.info("板块缓存预热已在后台启动（非阻塞，R44）")
    except (Exception, asyncio.CancelledError) as exc:
        logger.warning("板块缓存预热任务启动失败（非阻塞）：%s", exc)


# R59④ (round28): 设计链路数据预热——候选池 K 线缓存 + 因子矩阵。
# 旧实现 design 首呼撞冷 K 线缓存（refresh_kline 42-75s 全量建库）+ 数据源冷却
# → 90s 硬预算被吃光（round28 §14.4 task 559 超时失败）。sequence 末尾执行
# （此刻 pool 已由 _warmup_market_cache 填充），预算 25s 内完成 K 线缓存刷新，
# 使启动后首呼 design refresh ≤10s（热缓存）。后台 + 失败仅 WARNING 不阻塞启动。
async def _warmup_design_data(state) -> None:
    try:
        from ..services.market_data_hub import market_data_hub

        async def _do_design_warmup():
            _mark = state.warmup.setdefault("design_data", {
                "done": False, "success": False, "label": "设计数据（K线/因子）",
            })
            try:
                # 0. 等行情缓存预热任务收敛（refresh_market_cache 只刷实时报价，不填
                #    pool——但先让它跑完可减少启动期数据源并发争抢；150s 上限，超时
                #    仅 DEBUG，不阻塞 startup）。
                _mkt_task = getattr(state, "_market_warmup_task", None)
                if _mkt_task is not None:
                    try:
                        await asyncio.wait_for(asyncio.shield(_mkt_task), timeout=150)
                    except (Exception, asyncio.CancelledError):
                        logger.debug("[warmup] market warmup task wait timed out/failed (non-fatal)")
                # 1. refresh() 填充候选池——**唯一真实入口**（round28 实测：等 market
                #    warmup + 轮询 pool 恒空跳过，因为 refresh_market_cache 不写 _pool）。
                #    预算 150s 覆盖 scanner(≤90s)+分类+索引重建；失败仅降级跳过。
                try:
                    await asyncio.wait_for(market_data_hub.refresh(), timeout=150)
                except (Exception, asyncio.CancelledError) as exc:
                    logger.debug("[warmup] design-data refresh failed/timed out (non-fatal): %s", exc)
                # 2. 候选池读取（refresh 完成后 pool 已填充；冷却/TTL 跳过则用旧 pool）
                _syms: list[str] = []
                for _attempt in range(4):
                    try:
                        _pool = market_data_hub.get_pool()
                        _syms = list({str(it.get("symbol")) for layer in _pool.values()
                                      if isinstance(_pool, dict) and isinstance(layer, list)
                                      for it in layer if it.get("symbol") not in ("CASH",)})
                    except Exception:
                        _syms = []
                    if _syms:
                        break
                    await asyncio.sleep(2.0)
                if not _syms:
                    logger.debug("[warmup] design-data warmup skipped: pool empty after refresh")
                    _mark["done"] = True
                    _mark["success"] = False
                    return
                # 3. K 线缓存（磁盘缓存命中时秒级返回；miss 时 Semaphore(5) 并发拉取）
                # R88 (round30): 符号集 = pool ETF + 持仓个股（600519 等 A 股 / AAPL 等
                # US / 00700 等 HK）——个股不在 pool 内，不扩展则盘后 K 线空（§14.5）。
                _warm_syms = await _kline_warmup_symbols(_syms[:30])
                await asyncio.wait_for(market_data_hub.refresh_kline(_warm_syms), timeout=25)
                # 4. 因子矩阵预计算（factor_scores 随 pool 项挂载，无需单独预热——
                #    refresh_kline 已使 get_factor_matrix 首个调用命中缓存）
                _mark["done"] = True
                _mark["success"] = True
                logger.info("[warmup] design-data warmup done: %d pool symbols kline cached (R59④)",
                            len(_syms))
            except (Exception, asyncio.CancelledError) as exc:
                _mark["done"] = True
                _mark["success"] = False
                logger.debug("[warmup] design-data warmup failed (non-fatal): %s", exc)

        # 不 await：立即返回让 startup 就绪；实际预热在后台进行
        task = asyncio.create_task(_do_design_warmup())
        state._design_warmup_task = task
        logger.info("设计数据预热已在后台启动（非阻塞，R59④）")
    except (Exception, asyncio.CancelledError) as exc:
        logger.warning("设计数据预热任务启动失败（非阻塞）：%s", exc)


async def _warmup_sequence_task(state) -> None:
    # F3b (round27): 预热预算门禁——非阻塞 WARN。round27 §13.6 指出预热 profiler
    # 只写报告、无预算断言，导致 20s→34.5s 回归未被拦截。此处记录总耗时，超过
    # 阈值即结构化告警（不阻断启动、不影响请求），便于后续回归被捕获。
    # 阈值 30s：给 etf/instruments 冷拉（各自 90-120s 超时上限）留余量，
    # 同时能抓到「24s 快照 + 12.8s 空转」这类异常膨胀（34.5s 必触发）。
    _seq_start = time.time()
    _WARMUP_SEGMENTS.clear()
    try:
        # R170 (round52): 每个任务带 label → 分段耗时入 _WARMUP_SEGMENTS，
        # budget 告警与 warmup_timing.json 同口径（差额可归因到具体段）。
        await _run_warmup_sequence([
            ("market_cache", _warmup_market_cache(state)),
            ("etf_cache", _warmup_etf_cache(state)),
            ("global_indices", _warmup_global_indices(state)),
            ("sector_cache", _warmup_sector_cache(state)),
            ("instruments_sync", _background_instruments_sync()),
            ("indices_meta_sync", _background_indices_meta_sync()),
            # R59④ (round28): 设计链路数据预热——候选池 K 线缓存 + 因子矩阵。
            # 旧实现 design 首呼撞冷 K 线缓存（refresh_kline 42-75s 全量建库）
            # + 预热未完成时数据源冷却 → 90s 硬预算被吃光（task 559 超时失败）。
            # 预热 sequence 末尾执行（此刻 pool 已由 _warmup_market_cache 填充），
            # 后台 + 短预算（不阻塞 startup 就绪，失败仅 WARNING）。
            ("design_data", _warmup_design_data(state)),
        ])
    finally:
        _seq_elapsed = time.time() - _seq_start
        _WARMUP_BUDGET_S = float(os.environ.get("WARMUP_BUDGET_S", "30"))
        _msg = _format_warmup_budget_warning(
            _seq_elapsed, _WARMUP_BUDGET_S,
            list(_WARMUP_SEGMENTS), _warmup_uncovered_segments(),
        )
        if _seq_elapsed > _WARMUP_BUDGET_S:
            logger.warning(_msg)
        else:
            logger.info(_msg)


async def _delayed_sector_list_prefetch() -> None:
    try:
        await asyncio.sleep(30)
        await _warmup_sector_lists()
    except Exception:
        # round35 §11-T-①: 只捕 Exception——CancelledError 自然传播（任务已入
        # 容器，关停时必须可被取消），失败静默语义不变。
        logger.debug("[warmup] delayed sector list prefetch skipped (non-fatal)")
