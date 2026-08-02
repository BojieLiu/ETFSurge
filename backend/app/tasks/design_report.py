"""WebSocket design report composer"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from ..analysis.llm import generate_design_report

logger = logging.getLogger(__name__)

# In-memory connection manager for design report sessions
class DesignReportManager:
    def __init__(self):
        self._sessions: dict[str, set] = {}  # session_id -> set of ws references
        self._running: dict[str, bool] = {}   # session_id -> is LLM already running?

    def register(self, session_id: str, websocket) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = set()
        self._sessions[session_id].add(websocket)

    def unregister(self, session_id: str, websocket) -> None:
        if session_id in self._sessions:
            self._sessions[session_id].discard(websocket)
            if not self._sessions[session_id]:
                del self._sessions[session_id]

    async def broadcast(self, session_id: str, message: dict) -> None:
        if session_id not in self._sessions:
            return
        payload = json.dumps(message, ensure_ascii=False)
        dead = []
        for ws in self._sessions[session_id]:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.unregister(session_id, ws)

    def is_running(self, session_id: str) -> bool:
        return self._running.get(session_id, False)

    def mark_running(self, session_id: str, val: bool) -> None:
        self._running[session_id] = val


report_manager = DesignReportManager()


def _build_plan_tables(strategies: list[dict]) -> str:
    """P5-a: 从引擎 strategies 数据直接渲染方案详解 Markdown 表格。
    确保报告中的数据与方案卡片完全一致，杜绝 LLM 篡改标的。
    """
    # F3 R6: 首行不带 \n\n 前导（避免与 task_manager 前缀拼接后 3 个连续空行）
    lines = ["## 一、三种方案详解"]

    # ── 对比表：引擎直接渲染，LLM 不得篡改 ──
    labels = [s.get("label", "") for s in strategies]
    lines.append("\n### 方案对比总览\n")
    lines.append("| 维度 | " + " | ".join(labels) + " |")
    lines.append("|------|" + "|".join([":---:"] * len(strategies)) + "|")

    # 风格定位
    pos = [s.get("positioning", "—")[:20] for s in strategies]
    lines.append("| 风格定位 | " + " | ".join(pos) + " |")

    # ETF 数量/层结构
    cnts, cores, sats, defs = [], [], [], []
    for s in strategies:
        allocs = s.get("allocations") or s.get("etfs") or []
        core_w = sum(e.get("weight") or e.get("target_weight") or 0 for e in allocs if e.get("layer") in ("core",))
        sat_w  = sum(e.get("weight") or e.get("target_weight") or 0 for e in allocs if e.get("layer") in ("satellite", "sat"))
        def_w  = sum(e.get("weight") or e.get("target_weight") or 0 for e in allocs if e.get("layer") in ("defense", "defence"))
        cores.append(f"{core_w * 100:.0f}%")
        sats.append(f"{sat_w * 100:.0f}%")
        defs.append(f"{def_w * 100:.0f}%")
        etf_cnt = sum(1 for e in allocs if e.get("symbol") != "CASH")
        cnts.append(str(etf_cnt) + " 只")
    lines.append("| ETF 数量 | " + " | ".join(cnts) + " |")
    lines.append("| 核心层 | " + " | ".join(cores) + " |")
    lines.append("| 卫星层 | " + " | ".join(sats) + " |")
    lines.append("| 防御层 | " + " | ".join(defs) + " |")

    # 现金 / 预期回报
    cashes, rets, rets_current = [], [], []
    for s in strategies:
        allocs = s.get("allocations") or s.get("etfs") or []
        cash = next((e for e in allocs if e.get("symbol") == "CASH"), None)
        w = (cash.get("weight") or cash.get("target_weight") or 0) * 100 if cash else 10
        cashes.append(f"{w:.0f}%")
        r = s.get("expected_return")
        rets.append(f"{r * 100:.0f}%" if r is not None else "—")
        rc = s.get("expected_return_current")
        rets_current.append(f"{rc * 100:.0f}%" if rc is not None else "—")
    lines.append("| 现金仓位 | " + " | ".join(cashes) + " |")
    lines.append("| 预期年化 | " + " | ".join(rets) + " |")
    lines.append("| 当前预期年化 | " + " | ".join(rets_current) + " |")
    # P2-6 (R4-03): 「当前预期年化 == 预期年化」显式说明——避免默认同值被误读为
    # 「系统评估过当前市态且收益不变」；range_bound 市态 dynamic_layer_budget
    # 调整系数为 0（budgets.py adjust_expected_return），相等是设计行为。
    _no_adjust = bool(strategies) and all(
        s.get("expected_return_current") is None
        or (s.get("expected_return") is not None
            and abs((s.get("expected_return_current") or 0) - (s.get("expected_return") or 0)) < 1e-9)
        for s in strategies
    )
    if _no_adjust:
        lines.append(
            "\n> 注：当前预期年化与预期年化一致——当前市态未触发预期收益调整"
            "（震荡市态调整系数为 0，属设计行为，非数据异常）。"
        )

    for s in strategies:
        label = s.get("label", "")
        allocs = s.get("allocations") or s.get("etfs") or []
        core_pct = sum(e.get("weight") or e.get("target_weight") or 0 for e in allocs if e.get("layer") in ("core",)) * 100
        sat_pct = sum(e.get("weight") or e.get("target_weight") or 0 for e in allocs if e.get("layer") in ("satellite", "sat")) * 100
        def_pct = sum(e.get("weight") or e.get("target_weight") or 0 for e in allocs if e.get("layer") in ("defense", "defence")) * 100
        lines.append(f"\n### {label}")
        lines.append(f"资产结构：核心 {core_pct:.0f}% · 卫星 {sat_pct:.0f}% · 防御 {def_pct:.0f}%\n")
        lines.append("| 资产类别 | 代码 | 名称 | 权重 | 多因子评分 | 今日涨跌 | 入选理由 |")
        lines.append("|---------|------|------|:----:|:--------:|:-------:|---------|")

        allocs = s.get("allocations") or s.get("etfs") or []
        for e in allocs:
            if e.get("symbol") == "CASH":
                continue
            code = e.get("symbol", "")
            # F3 R5: 名称不截断（旧 [:12] 产生"中证500增强ETF易方"类残句）
            name = e.get("name", "")
            w = (e.get("weight") or e.get("target_weight") or 0) * 100
            raw = e.get("selection_rationale") or ""
            # F3 R4 用户决策更新（2026-08-02）：理由不再截断——与 R5 名称处理一致，
            # markdown 表格渲染自动换行；完整理由保留估值/资金流/市态等关键尾部。
            # 竖线转义 + 换行展平：防止 rationale 含 `|`/`\n`（如风控追加文本）拆裂表格行。
            rationale = raw.replace("|", "\\|").replace("\n", " ").replace("\r", "")
            layer_en = e.get("layer", "—")
            layer_cn = {"core": "核心", "satellite": "卫星", "sat": "卫星", "defense": "防御", "defence": "防御", "cash": "现金"}.get(layer_en, layer_en)
            fs = e.get("factor_score", None)
            fs_txt = f"{fs:.2f}" if fs is not None else ""
            dcp = e.get("daily_change_pct")
            if dcp is not None:
                dcp_txt = f"{dcp * 100:.2f}%" if abs(dcp) < 1 else f"{dcp:.2f}%"
                dcp_txt = ("+" if dcp >= 0 else "") + dcp_txt
            else:
                # P1-4 (R4-02): 涨跌数据缺失显性化——输出「数据源不可用」而非 "—"，
                # 避免「数据源降级导致的数据缺失」被误读为「0% 涨跌」或静默缺失。
                dcp_txt = "数据源不可用"
            lines.append(f"| {layer_cn} | {code} | {name} | {w:.0f}% | {fs_txt} | {dcp_txt} | {rationale} |")

    lines.append("\n> 注：多因子评分（0~1）基于资金流、估值、动量、流动性等维度综合计算，非涨跌幅。")
    return "\n".join(lines)


def _strip_ai_boilerplate(text: str | None) -> str:
    """去除 LLM 报告中的 AI 腔开头和虚构元数据行。

    移除：
      - 以"好的"/"作为专业"/"ETT 投资…"等开头的 AI 腔段落
      - "报告日期："/"**报告日期" 行
      - "分析师："/"**分析师" 行
      - 独立的 "### ETF 投资组合策略报告" 标题行
    """
    if not text:
        return text or ""
    import re

    lines = text.split("\n")
    cleaned = []
    in_header = True

    # 通用 AI 腔行检测（不论位置）
    def _is_ai_crust(stripped: str) -> bool:
        if not stripped:
            return False
        if re.match(r"\*\*报告日期", stripped) or re.match(r"报告日期", stripped):
            return True
        if re.match(r"\*\*分析师", stripped) or re.match(r"分析师", stripped):
            return True
        if re.match(r"^#(#)?\s*ETF\s*投资", stripped):
            return True
        if re.match(r"^好的，作为专业", stripped):
            return True
        return False

    for line in lines:
        stripped = line.strip()

        # 文档开头：跳过 AI 腔段落（包括空行前后的连续 AI 腔）
        if in_header and (
            "好的" in stripped[:10]
            or "作为专业" in stripped[:10]
            or "作为一名" in stripped[:10]
            or _is_ai_crust(stripped)
        ):
            continue

        # 文档中后部：只要有通用 AI 腔模式也跳过
        if _is_ai_crust(stripped):
            continue

        in_header = False
        cleaned.append(line)

    return "\n".join(cleaned).strip()


def _count_repeated_headers(text: str) -> int:
    """Count duplicate markdown headers (same heading text at any level).

    Returns the number of headers that appear more than once.
    """
    import re
    headers = re.findall(r'^#{1,6}\s+.*$', text, re.MULTILINE)
    seen: set[str] = set()
    repeats = 0
    for h in headers:
        if h in seen:
            repeats += 1
        seen.add(h)
    return repeats


def _dedup_headers(text: str) -> str:
    """F3 R2/R3: 轻量标题去重 + 空行规范化（所有写库路径共用）。

    检出重复标题即回写修正（不只看 warning）；空行 \n{3,} → \n\n。
    """
    import re
    if not text:
        return text
    lines = text.split("\n")
    seen: dict[str, int] = {}
    out: list[str] = []
    for line in lines:
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            key = f"{m.group(1)}|{m.group(2).strip()}"
            if key in seen:
                continue  # 丢弃重复标题行
            seen[key] = len(out)
        out.append(line)
    text = "\n".join(out)
    # R6: 空行 3+ → 2（旧实现保留 3 空行仍偏多）
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _validate_design_text(design_text: str) -> list[str]:
    """Validate design report content completeness and quality.

    Returns a list of warning strings (empty = no issues).
    """
    warnings: list[str] = []
    if "## 一、三种方案详解" not in design_text:
        warnings.append("缺少方案详解标题")
    if _count_repeated_headers(design_text) > 0:
        warnings.append("存在重复标题")
    # Check for truncated descriptions
    for line in design_text.splitlines():
        if "适合中等风" in line and "险偏好" not in line:
            warnings.append("存在截断描述")
            break
    # Minimum length check
    if len(design_text) < 200:
        warnings.append("报告内容过短")
    return warnings


def _validate_report_consistency(report_text: str, strategies: list[dict]) -> str:
    """校验 LLM 报告中的 ETF 代码是否与引擎策略数据一致。
    如 LLM 引入了引擎方案以外的标的，追加修正脚注。
    如 LLM 遗漏了三个方案中的某个，追加提醒段落。
    
    Q04 增强:
    - 检查所有方案是否均为 CASH（无真实 ETF），追加明确警告
    - 若策略 ETF 数为 0，在报告中追加修正脚注
    
    P1 增强 (system-diagnosis):
    - 检测重复章节标题，追加修正脚注
    - 折叠 3+ 连续空行为最多 2 行
    """
    import re

    fixes_applied = 0

    # ── 重复章节标题检测 ──
    headers = re.findall(r"^(##+)\s+(.+)$", report_text, re.MULTILINE)
    seen_headers: dict[str, list[int]] = {}
    dup_lines: list[int] = []
    for i, (level, title) in enumerate(headers):
        key = f"{level}|{title.strip()}"
        if key in seen_headers:
            dup_lines.append(i)
        else:
            seen_headers[key] = [i]
    if dup_lines:
        logger.warning(
            "[design_report] Detected %d duplicate section headers in LLM report",
            len(dup_lines),
        )
        dup_note = (
            "\n\n> **📝 格式说明**：报告存在重复章节标题，已自动去重。"
            "请以方案卡片中的完整方案信息为准。"
        )
        report_text += dup_note
        fixes_applied += len(dup_lines)
        # Remove duplicate header lines from the text
        lines = report_text.split("\n")
        # Track which header lines (by index in lines) are duplicates
        header_line_indices: dict[str, int] = {}  # key -> first occurrence line index
        dedup_lines = []
        for line in lines:
            m = re.match(r"^(##+)\s+(.+)$", line)
            if m:
                key = f"{m.group(1)}|{m.group(2).strip()}"
                if key in header_line_indices:
                    # Skip duplicate header line
                    fixes_applied += 1
                    continue
                header_line_indices[key] = len(dedup_lines)
            dedup_lines.append(line)
        report_text = "\n".join(dedup_lines)

    # ── 空白行规范化 ──
    original_len = len(report_text)
    # R6: 空行规范化——3+ 连续空行压到 2（与 _dedup_headers 同规格，避免 LLM 空行堆叠）
    report_text = re.sub(r"\n{3,}", "\n\n", report_text)
    collapsed = original_len - len(report_text)
    if collapsed > 0:
        logger.info(
            "[design_report] Collapsed %d chars of excess blank lines in LLM report",
            collapsed,
        )
        fixes_applied += 1

    # ── 提取引擎策略中的所有 ETF 代码 ──
    engine_symbols: set[str] = set()
    total_real_etfs = 0
    for s in strategies:
        for a in s.get("allocations") or s.get("etfs") or []:
            sym = a.get("symbol", "")
            if sym and sym != "CASH":
                engine_symbols.add(sym)
                total_real_etfs += 1

    # Q04: 检查是否所有方案均为空（无真实 ETF）
    if total_real_etfs == 0:
        logger.warning(
            "[design_report] All strategies have 0 real ETFs — appending empty allocation footnote"
        )
        empty_note = (
            "\n\n> **⚠️ 方案数据说明**：当前所有方案均无真实 ETF 标的（100%现金），"
            "因子评分均低于选标阈值或数据源不可用。"
            "建议在市场数据恢复正常后重新生成设计方案。"
        )
        report_text += empty_note
        return report_text

    # 提取报告中所有 ETF 代码（6 位纯数字）
    report_symbols: set[str] = set(re.findall(r"\b(\d{6})\b", report_text))

    # 差集：LLM 写了哪些引擎没有的标的
    extra_symbols = report_symbols - engine_symbols
    if extra_symbols:
        logger.error(
            "[design_report] LLM introduced %d symbols outside engine pool: %s",
            len(extra_symbols), sorted(extra_symbols)
        )
        extra_note = (
            "\n\n> **⚠️ 一致性说明**：以下代码在报告中出现但不在引擎方案中："
            + ", ".join(sorted(extra_symbols))
            + "。以上分析仅供参考，实际配置以方案卡片中的 ETF 标的和权重为准。"
        )
        report_text += extra_note
        fixes_applied += 1

    # 检查是否覆盖了三种方案
    plan_names = [s.get("label", "") or s.get("style", "") for s in strategies]
    missing = []
    for n in plan_names:
        if not n:
            continue
        if n in report_text:
            continue
        # 容忍别名匹配：LLM 可能用 positioning/portfolio_name 而非 label
        s_match = [s for s in strategies if (s.get("label") == n or s.get("style") == n)]
        if s_match:
            pos = s_match[0].get("positioning", "") or s_match[0].get("portfolio_name", "")
            if pos and pos in report_text:
                continue
        missing.append(n)
    if missing:
        miss_note = (
            "\n\n> **📋 方案说明**：系统共生成 "
            + "、".join(plan_names)
            + " 三个方案，报告未完整展开的方案请参考「方案卡片」Tab 查看完整明细。"
        )
        report_text += miss_note
        fixes_applied += 1

    if fixes_applied > 0:
        logger.info(
            "[design_report] _validate_report_consistency applied %d total fixes",
            fixes_applied,
        )

    return report_text


async def compose_and_push_report(
    session_id: str,
    strategies: list[dict],
    market_sentiment: dict | None = None,
    benchmark_stocks: list[dict] | None = None,
    market_context: dict | None = None,
    design_id: int | None = None,  # 传 design_id 时，报告完成后写回数据库
) -> None:
    """生成 LLM 报告并通过 WS 推送。

    P1 增强：新增 market_context 参数，透传完整市场上下文（含 index_realtime /
    market_regime / macro_regime / sector_momentum）给 LLM 报告，取代仅用
    market_sentiment + benchmark_stocks 的狭窄输入。旧调用（仅传前两个字段）
    仍向后兼容。

    流程:
      1. 推送 status=generating, progress=10
      2. 调用 LLM generate_design_report
      3. 推送 chunks (status=streaming)
      4. 推送 complete (status=complete) 或 error
    """
    if report_manager.is_running(session_id):
        logger.info("[design_report] session %s already running, skipping", session_id)
        return

    report_manager.mark_running(session_id, True)
    try:
        # 推送进度: 开始
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "generating",
            "progress": 10,
            "stage": "正在分析市场环境...",
        })

        # P5-a: 先生成策略表格（引擎直接渲染，确保与方案卡片一致）
        plan_tables = _build_plan_tables(strategies)

        # 调用 LLM，注入预生成的策略表格，让 LLM 只写分析部分
        try:
            llm_analysis = await asyncio.wait_for(
                generate_design_report(
                    strategies=strategies,
                    market_sentiment=market_sentiment,
                    benchmark_stocks=benchmark_stocks,
                    market_context=market_context,
                    plan_tables=plan_tables,
                ),
                timeout=240,
            )
        except (asyncio.TimeoutError, TimeoutError):
            logger.error("[design_report] LLM generation timed out after 240s, using fallback summary")
            llm_analysis = None

        if llm_analysis:
            report_text = plan_tables + "\n\n## 二、市场环境与配置建议\n\n" + llm_analysis
        else:
            logger.warning("[design_report] LLM empty, using engine tables only")
            report_text = "# ETF 组合设计方案（数据摘要）\n" + plan_tables

        # P10: 后处理 — 去除 AI 腔开头和虚构元数据
        report_text = _strip_ai_boilerplate(report_text)

        if not report_text:
            logger.warning("[design_report] LLM returned empty, generating fallback summary")
            fallback_parts = [
                "# ETF 组合设计方案（数据摘要）\n",
                f"市场状态：{market_context.get('market_regime', '—')}\n",
            ]
            for s in strategies:
                label = s.get("label", "")
                lb = s.get("layer_budget", {})
                fallback_parts.append(f"\n## {label}\n")
                fallback_parts.append(f"核心 {lb.get('core',0)*100:.0f}% · 卫星 {lb.get('satellite',0)*100:.0f}% · 防御 {lb.get('defense',0)*100:.0f}%\n\n")
                for e in (s.get("allocations") or s.get("etfs") or []):
                    if e.get("symbol") == "CASH": continue
                    w = (e.get("weight") or e.get("target_weight") or 0) * 100
                    fallback_parts.append(f"- {e.get('name','')} ({e.get('symbol')}) {w:.0f}% — {e.get('selection_rationale','')[:80]}\n")
            report_text = "".join(fallback_parts)
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "complete",
                "report_text": report_text,
            })
            # 写库
            if design_id is not None:
                try:
                    from ..database import async_session
                    from ..models.portfolio_design import PortfolioDesign
                    async with async_session() as db:
                        d = await db.get(PortfolioDesign, design_id)
                        if d:
                            d.design_text = report_text
                            await db.commit()
                except Exception as pe:
                    logger.error("[design_report] fallback persist error: %s", pe)
            return

        # 推送进度: 撰写完成
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "generating",
            "progress": 60,
            "stage": "报告撰写完成，正在格式化...",
        })

        # 按段落推送 chunks（模拟流式）
        paragraphs = report_text.split("\n\n")
        for i, para in enumerate(paragraphs):
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "streaming",
                "chunk": para + "\n\n",
            })
            progress = 60 + int(40 * (i + 1) / max(len(paragraphs), 1))
            await report_manager.broadcast(session_id, {
                "type": "design_report",
                "session_id": session_id,
                "status": "generating",
                "progress": min(progress, 95),
                "stage": "传输中...",
            })
            await asyncio.sleep(0.05)  # 模拟流式延时

        # 一致性校验：对比 LLM 报告的 ETF 代码与引擎策略数据
        try:
            report_text = _validate_report_consistency(report_text, strategies)
        except Exception as ve:
            logger.warning("[design_report] consistency check failed (non-blocking): %s", ve)

        # 推送完成
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "complete",
            "report_text": report_text,
        })

        # 持久化：将报告文本写入数据库（如果传了 design_id）
        if design_id is not None and report_text:
            try:
                from ..database import async_session
                from ..models.portfolio_design import PortfolioDesign
                async with async_session() as db:
                    design = await db.get(PortfolioDesign, design_id)
                    if design:
                        design.design_text = report_text
                        await db.commit()
                        logger.info("[design_report] persisted design_text for design %s", design_id)
                    else:
                        logger.warning("[design_report] design %s not found for persist", design_id)
            except Exception as persist_e:
                logger.error("[design_report] failed to persist design_text: %s", persist_e)



    except asyncio.TimeoutError:
        logger.warning("[design_report] LLM timeout for session %s, saving fallback", session_id)
        _fallback = plan_tables + """

---

## 市场环境概览

> ⚠️ AI 深度分析报告生成超时，以下为基于引擎数据的自动摘要。

### 方案说明
以上三套方案（防御型/平衡型/进攻型）由策略引擎基于实时市场数据和24+因子模型自动生成：
- **因子评分**：每只ETF的综合因子评分越高代表多维度综合表现越好
- **市场状态**：引擎已识别当前市场状态（趋势/震荡/牛/熊）并相应调整各层预算
- **权重分配**：遵守风控约束（单只≤30%、行业集中度<40%、层预算不超标）

### 操作建议
- 选择符合您风险偏好的方案，点击「应用此方案」将配置保存到组合
- 如需更深入的LLM分析报告，稍后重新生成即可
- 当前方案可直接用于交易参考
"""
        if design_id is not None:
            try:
                from ..database import async_session as _dbs
                from ..models.portfolio_design import PortfolioDesign
                async with _dbs() as _db:
                    d = await _db.get(PortfolioDesign, design_id)
                    if d:
                        d.design_text = _fallback
                        await _db.commit()
                        logger.info("[design_report] saved fallback for design %s", design_id)
            except Exception as pe:
                logger.error("[design_report] fallback persist failed: %s", pe)
        await report_manager.broadcast(session_id, {
            "type": "design_report", "session_id": session_id,
            "status": "complete", "report_text": _fallback,
        })
        return

    except Exception as e:
        logger.error("[design_report] error for session %s: %s", session_id, e, exc_info=True)
        await report_manager.broadcast(session_id, {
            "type": "design_report",
            "session_id": session_id,
            "status": "error",
            "message": f"报告生成异常: {e}",
        })
    finally:
        report_manager.mark_running(session_id, False)
