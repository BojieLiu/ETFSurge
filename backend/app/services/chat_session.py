"""ChatSessionStore — LLM 多轮对话会话存储（round53 §9 阶段 1+2）。

两层结构（§9.2 拍板）:
- 内存层: LRU（上限 CHAT_STORE_CAPACITY=100）+ TTL（CHAT_SESSION_TTL=30min），
  热路径（每次追问先查）+ 市场快照 60s 复用（CHAT_CONTEXT_TTL，省 5s+/轮重采集）；
- SQLite 层: chat_sessions 表（24h TTL），本轮 done 时 upsert，启动时加载未过期
  会话恢复 L1；读取时惰性过期。

护栏（§9.3 拍板）: 历史注入最近 CHAT_HISTORY_MAX_ROUNDS=10 条消息 +
estimate_tokens 总预算 CHAT_HISTORY_TOKEN_BUDGET=8K（超出截最旧轮）。
契约: api-contracts/analysis/llm-chat-session.md
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from app.models.chat_session import ChatSessionRecord
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ── 护栏常量（§9.2/§9.3 拍板值） ──────────────────────────────────────
CHAT_STORE_CAPACITY = 100          # LRU 会话上限
CHAT_SESSION_TTL = 30 * 60         # 内存会话 TTL（秒，无活动过期）
CHAT_CONTEXT_TTL = 60              # 市场快照复用窗口（秒）
CHAT_HISTORY_MAX_ROUNDS = 10       # prompt 注入最近消息条数上限
CHAT_HISTORY_TOKEN_BUDGET = 8_000  # prompt 历史槽 token 预算
CHAT_PERSIST_TTL_HOURS = 24        # SQLite 持久层 TTL（小时）

_BEIJING_TZ = timezone(timedelta(hours=8))


def estimate_tokens(text: str) -> int:
    """粗估 token 数：CJK 字符 ≈1 token/字，ASCII ≈1 token/4 字符。

    LLM 上下文预算用（非计费口径）——中英混合文本的快速上限估计。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if '\u4e00' <= ch <= '\u9fff')
    other = len(text) - cjk
    return cjk + max(1, other // 4)


class ChatSessionStore:
    """内存 LRU + SQLite 持久双层会话存储。"""

    def __init__(self, capacity: int = CHAT_STORE_CAPACITY):
        self._sessions: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._capacity = capacity

    # ── 内存层 ────────────────────────────────────────────────────────

    def start_or_get(self, session_id: str | None, expect_type: str | None = None) -> tuple[str, list[dict]]:
        """取会话；session_id 缺失/无效/过期 → 开新会话（不报错）。

        expect_type: 会话类型隔离（advice/report/symbol）——命中但类型不符
            视为串话，自动开新会话。None=不校验（兼容旧调用）。
        Returns:
            (生效的 session_id, 完整历史消息列表)
        """
        now = datetime.now()
        if session_id and session_id in self._sessions:
            entry = self._sessions[session_id]
            if now - entry["last_active"] < timedelta(seconds=CHAT_SESSION_TTL):
                if expect_type is not None and entry.get("session_type", "advice") != expect_type:
                    logger.info("[chat_session] %s type mismatch (%s!=%s), starting new",
                                session_id, entry.get("session_type"), expect_type)
                else:
                    # LRU touch
                    self._sessions.move_to_end(session_id)
                    entry["last_active"] = now
                    return session_id, list(entry["messages"])
            else:
                # TTL 过期 → 丢弃重建
                logger.info("[chat_session] %s expired (memory TTL), starting new", session_id)
                del self._sessions[session_id]
        return self._create(session_type=expect_type or "advice")

    def _create(self, session_type: str = "advice") -> tuple[str, list[dict]]:
        sid = f"sess-{uuid.uuid4().hex[:16]}"
        self._sessions[sid] = {"messages": [], "last_active": datetime.now(),
                               "market_snapshot": None, "snapshot_ts": None,
                               "session_type": session_type,
                               "market": None, "symbol": None,
                               "frozen_snapshot": None}
        self._sessions.move_to_end(sid)
        self._evict_overflow()
        return sid, []

    def _evict_overflow(self) -> None:
        while len(self._sessions) > self._capacity:
            evicted, _ = self._sessions.popitem(last=False)
            logger.debug("[chat_session] LRU evicted %s", evicted)

    def append(self, session_id: str, message: dict) -> None:
        """追加消息（user / assistant）；会话不存在则忽略（防御）。"""
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        entry["messages"].append({
            "role": message.get("role", "user"),
            "content": str(message.get("content", "")),
            "ts": message.get("ts") or datetime.now().timestamp(),
        })
        entry["last_active"] = datetime.now()
        self._sessions.move_to_end(session_id)

    def history_window(self, session_id: str) -> list[dict]:
        """prompt 注入窗口：最近 N 条消息 + token 预算内（超出截最旧）。"""
        entry = self._sessions.get(session_id)
        if entry is None:
            return []
        window = entry["messages"][-CHAT_HISTORY_MAX_ROUNDS:]
        # token 预算：从最新往回收，超预算的旧消息截掉
        kept: list[dict] = []
        total = 0
        for m in reversed(window):
            cost = estimate_tokens(m["content"])
            if total + cost > CHAT_HISTORY_TOKEN_BUDGET and kept:
                break
            # 单条超预算也保留骨架（截内容），保证最新一轮永远在场
            if cost > CHAT_HISTORY_TOKEN_BUDGET:
                m = {**m, "content": m["content"][: CHAT_HISTORY_TOKEN_BUDGET * 2]}
                cost = estimate_tokens(m["content"])
            total += cost
            kept.append(m)
        kept.reverse()
        return kept

    def render_history(self, session_id: str) -> str:
        """渲染「## 对话历史」prompt 槽；空历史返回空串（不注入）。"""
        window = self.history_window(session_id)
        if not window:
            return ""
        lines = ["## 对话历史"]
        for m in window:
            role = "用户" if m["role"] == "user" else "助手"
            content = m["content"].replace("\n", " ")[:500]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)

    # ── 市场快照复用（60s） ──────────────────────────────────────────

    def set_frozen(self, session_id: str, snapshot: Any, market: str | None = None,
                   symbol: str | None = None) -> None:
        """冻结首轮快照（report/symbol 追问链路，会话内只读不采）。"""
        entry = self._sessions.get(session_id)
        if entry is None:
            return
        entry["frozen_snapshot"] = snapshot
        if market is not None:
            entry["market"] = market
        if symbol is not None:
            entry["symbol"] = symbol
        entry["last_active"] = datetime.now()
        self._sessions.move_to_end(session_id)

    def get_frozen(self, session_id: str) -> Any:
        """取冻结快照；缺失返回 None（调用方回退重采并重新冻结）。"""
        entry = self._sessions.get(session_id)
        if entry is None:
            return None
        return entry.get("frozen_snapshot")

    def get_market_snapshot(self, session_id: str, collector: Callable[[], Any]) -> Any:
        """TTL 内复用本会话市场快照；过期/缺失时调用 collector 重采。"""
        entry = self._sessions.get(session_id)
        if entry is None:
            return collector()
        now = datetime.now()
        snap = entry.get("market_snapshot")
        ts = entry.get("snapshot_ts")
        if snap is not None and ts is not None and now - ts < timedelta(seconds=CHAT_CONTEXT_TTL):
            return snap
        fresh = collector()
        entry["market_snapshot"] = fresh
        entry["snapshot_ts"] = now
        return fresh

    # ── SQLite 持久层 ────────────────────────────────────────────────

    async def persist_session(self, db, session_id: str) -> bool:
        """会话 upsert 到 chat_sessions（本轮 done 时调用；失败不阻塞主流程）。"""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        entry = self._sessions.get(session_id)
        if entry is None:
            return False
        try:
            stmt = sqlite_insert(ChatSessionRecord).values(
                session_id=session_id,
                messages_json=json.dumps(entry["messages"], ensure_ascii=False),
                updated_at=datetime.utcnow(),
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["session_id"],
                set_={"messages_json": json.dumps(entry["messages"], ensure_ascii=False),
                      "updated_at": datetime.utcnow()},
            )
            await db.execute(stmt)
            await db.commit()
            return True
        except Exception as e:
            logger.warning("[chat_session] persist %s failed: %s", session_id, e)
            return False

    async def load_persisted(self, db, max_age_hours: float = CHAT_PERSIST_TTL_HOURS) -> dict[str, list[dict]]:
        """启动恢复：加载 24h 内会话到内存 L1；过期行惰性删除。

        Returns:
            {session_id: messages}（已灌入本 store 内存层）
        """
        from sqlalchemy import delete, select

        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        restored: dict[str, list[dict]] = {}
        try:
            rows = (await db.execute(select(ChatSessionRecord))).scalars().all()
            stale_ids: list[str] = []
            for row in rows:
                if row.updated_at and row.updated_at < cutoff:
                    stale_ids.append(row.session_id)
                    continue
                try:
                    messages = json.loads(row.messages_json or "[]")
                except (TypeError, ValueError):
                    stale_ids.append(row.session_id)
                    continue
                if not isinstance(messages, list):
                    stale_ids.append(row.session_id)
                    continue
                self._sessions[row.session_id] = {
                    "messages": messages,
                    "last_active": datetime.now(),
                    "market_snapshot": None,
                    "snapshot_ts": None,
                }
                restored[row.session_id] = messages
            # LRU 容量保护（恢复不挤爆热路径）
            while len(self._sessions) > self._capacity:
                self._sessions.popitem(last=False)
            if stale_ids:
                await db.execute(delete(ChatSessionRecord).where(
                    ChatSessionRecord.session_id.in_(stale_ids)))
                await db.commit()
                logger.info("[chat_session] lazy-expired %d stale sessions", len(stale_ids))
        except Exception as e:
            logger.warning("[chat_session] load_persisted failed: %s", e)
        return restored


# 全局单例（模块导入即建，无 DB 依赖；DB 恢复在 lifespan 挂载）
chat_store = ChatSessionStore()


def get_chat_store() -> ChatSessionStore:
    return chat_store
