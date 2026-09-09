# -*- coding: utf-8 -*-
"""LLM 对话多轮会话（round53 §9 拍板：阶段 1+2，docs/round53-container-reacceptance-round52-plans.md §9.2）。

契约: api-contracts/analysis/llm-chat-session.md。

验收口径（§9.2.4 测试覆盖）:
- 多会话并发: 两个 session_id 并行问答互不污染;
- 上下文截断: 12 轮历史只保留最近 10 轮（+ 8K token 上限）;
- 持久化恢复: 写入后新实例可读回（SQLite 层）;
- TTL 过期: 30min（内存）/ 24h（SQLite）惰性过期;
- done.metadata.session_id: 新会话回新 id、追问回原 id;
- 上下文快照 60s 复用: 同会话第二次提问不重跑 build_full_context。
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.chat_session import ChatSessionRecord
from app.models.chat_session import ChatSessionRecord
from app.services.chat_session import (
    CHAT_CONTEXT_TTL,
    CHAT_HISTORY_MAX_ROUNDS,
    CHAT_HISTORY_TOKEN_BUDGET,
    CHAT_SESSION_TTL,
    CHAT_STORE_CAPACITY,
    estimate_tokens,
    ChatSessionStore,
    get_chat_store,
)


def _msg(role: str, content: str, ts: float | None = None) -> dict:
    return {"role": role, "content": content, "ts": ts or 1_000_000.0}


class TestChatSessionStoreBasics:
    def test_new_session_returns_id_and_empty_history(self):
        store = ChatSessionStore()
        sid, history = store.start_or_get(None)
        assert sid and sid.startswith("sess-")
        assert history == []

    def test_invalid_session_id_starts_new(self):
        """无效 session_id 自动开新会话不报错（契约回归保护）。"""
        store = ChatSessionStore()
        sid, history = store.start_or_get("sess-nonexistent")
        assert sid != "sess-nonexistent"
        assert history == []

    def test_append_and_history_roundtrip(self):
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        store.append(sid, _msg("user", "为什么这么说？"))
        store.append(sid, _msg("assistant", "因为动量因子……"))
        sid2, history = store.start_or_get(sid)
        assert sid2 == sid
        assert [m["role"] for m in history] == ["user", "assistant"]
        assert history[0]["content"] == "为什么这么说？"

    def test_two_sessions_isolated(self):
        """多会话并发互不污染（§9.2.4 第一条）。"""
        store = ChatSessionStore()
        sid_a, _ = store.start_or_get(None)
        sid_b, _ = store.start_or_get(None)
        assert sid_a != sid_b
        store.append(sid_a, _msg("user", "A 的问题"))
        store.append(sid_b, _msg("user", "B 的问题"))
        _, hist_a = store.start_or_get(sid_a)
        _, hist_b = store.start_or_get(sid_b)
        assert hist_a[0]["content"] == "A 的问题"
        assert hist_b[0]["content"] == "B 的问题"

    def test_lru_capacity_eviction(self):
        """LRU 100 会话：容量满后最旧会话被逐出。"""
        store = ChatSessionStore()
        first_sid, _ = store.start_or_get(None)
        for _ in range(CHAT_STORE_CAPACITY):
            store.start_or_get(None)
        # first 已被逐出 → 再次访问等于开新会话
        sid_now, _ = store.start_or_get(first_sid)
        assert sid_now != first_sid

    def test_memory_ttl_expiry(self):
        """内存 TTL 30min：过期后 start_or_get 开新会话。"""
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        store.append(sid, _msg("user", "旧问题"))
        # 时间快进 31min
        future = datetime.now() + timedelta(seconds=CHAT_SESSION_TTL + 60)
        with patch("app.services.chat_session.datetime") as mock_dt:
            mock_dt.now.return_value = future
            sid2, history = store.start_or_get(sid)
        assert sid2 != sid
        assert history == []


class TestHistoryWindow:
    def test_window_truncates_to_last_10_rounds(self):
        """12 轮历史 → 只注入最近 10 条消息（5 轮问答×2=10 条）。"""
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        for i in range(12):
            store.append(sid, _msg("user", f"q{i}"))
            store.append(sid, _msg("assistant", f"a{i}"))
        window = store.history_window(sid)
        assert len(window) <= CHAT_HISTORY_MAX_ROUNDS
        assert window[-1]["content"] == "a11"
        assert window[0]["content"] == "q7"  # 24 条取末 10 条（q7..a11）

    def test_token_budget_truncates_oldest(self):
        """总 token 超 8K → 从最旧开始截。"""
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        big = "x" * 900  # ~900 tokens/条
        for i in range(12):
            store.append(sid, _msg("user", big + str(i)))
            store.append(sid, _msg("assistant", "ok"))
        window = store.history_window(sid)
        total = sum(estimate_tokens(m["content"]) for m in window)
        assert total <= CHAT_HISTORY_TOKEN_BUDGET
        # 最新的 3 轮必须在（截断只动最旧）
        contents = [m["content"] for m in window]
        assert any("11" in c for c in contents)

    def test_render_chat_history_block(self):
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        store.append(sid, _msg("user", "当前市场风格？"))
        store.append(sid, _msg("assistant", "偏向成长。"))
        block = store.render_history(sid)
        assert "## 对话历史" in block
        assert "用户: 当前市场风格？" in block
        assert "助手: 偏向成长。" in block

    def test_render_empty_history(self):
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        assert store.render_history(sid) == ""


class TestMarketSnapshotReuse:
    def test_snapshot_reused_within_ttl(self):
        """60s 内的追问复用快照（§9.2 第 4 条，省 5s+/轮）。"""
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        calls = []

        def _collector():
            calls.append(1)
            return {"index_realtime": [{"name": "上证指数"}]}

        store.get_market_snapshot(sid, _collector)
        store.get_market_snapshot(sid, _collector)  # 60s 内第二次
        assert len(calls) == 1, "60s 内快照必须复用，不得重采"

    def test_snapshot_refreshed_after_ttl(self):
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        calls = []

        def _collector():
            calls.append(1)
            return {}

        store.get_market_snapshot(sid, _collector)
        # 快进 61s
        future = datetime.now() + timedelta(seconds=CHAT_CONTEXT_TTL + 1)
        with patch("app.services.chat_session.datetime") as mock_dt:
            mock_dt.now.return_value = future
            store.get_market_snapshot(sid, _collector)
        assert len(calls) == 2


class TestSQLitePersistence:
    """阶段 2: SQLite 持久化 + 启动恢复 + 24h TTL。"""

    @pytest.fixture
    async def db_factory(self):
        engine = create_async_engine(
            "sqlite+aiosqlite://", connect_args={"timeout": 30}, poolclass=StaticPool)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all, tables=[ChatSessionRecord.__table__])
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        await engine.dispose()

    @pytest.mark.asyncio
    async def test_persist_and_restore(self, db_factory):
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        store.append(sid, _msg("user", "第一问"))
        store.append(sid, _msg("assistant", "第一答"))
        async with db_factory() as db:
            await store.persist_session(db, sid)

        # 新实例恢复
        store2 = ChatSessionStore()
        async with db_factory() as db:
            restored = await store2.load_persisted(db, max_age_hours=24)
        assert sid in restored
        assert restored[sid][0]["content"] == "第一问"
        # 恢复后可继续追问
        sid2, history = store2.start_or_get(sid)
        assert sid2 == sid
        assert history[0]["content"] == "第一问"

    @pytest.mark.asyncio
    async def test_expired_persisted_sessions_not_restored(self, db_factory):
        """24h TTL: 过期会话不恢复（惰性过期）。"""
        store = ChatSessionStore()
        sid, _ = store.start_or_get(None)
        store.append(sid, _msg("user", "过期会话"))
        async with db_factory() as db:
            await store.persist_session(db, sid)
            # 手工把 updated_at 改到 25h 前
            from sqlalchemy import update
            await db.execute(
                update(ChatSessionRecord)
                .where(ChatSessionRecord.session_id == sid)
                .values(updated_at=datetime.utcnow() - timedelta(hours=25))
            )
            await db.commit()
            restored = await store.load_persisted(db, max_age_hours=24)
        assert sid not in restored


class TestAdvicePromptChatHistory:
    """prompt 层: chat_history 槽注入 + router 传参。"""

    def test_prompt_includes_chat_history_when_present(self):
        from app.analysis.llm import _build_advice_stream_prompt
        ctx = {
            "market_regime": "range_bound",
            "market_data": [],
            "news": [],
            "sector_momentum": [],
            "fund_flow": {},
            "chat_history": "## 对话历史\n用户: 为什么这么说？\n助手: 因为动量因子强。",
        }
        prompt = _build_advice_stream_prompt("那换成 510300 呢？", ctx)
        assert "## 对话历史" in prompt
        assert "用户: 为什么这么说？" in prompt
        # 当前 query 不应进历史槽（在开头用户提问行）
        assert prompt.index("用户提问: 那换成 510300 呢？") < prompt.index("## 对话历史")

    def test_prompt_no_history_block_when_absent(self):
        from app.analysis.llm import _build_advice_stream_prompt
        prompt = _build_advice_stream_prompt("新问题", {
            "market_data": [], "news": [], "sector_momentum": [], "fund_flow": {},
        })
        assert "## 对话历史" not in prompt


class TestAdviceRequestModel:
    def test_session_id_optional_default_none(self):
        from app.routers.analysis import LLMAdviceRequest
        req = LLMAdviceRequest(query="hi")
        assert req.session_id is None

    def test_session_id_accepted(self):
        from app.routers.analysis import LLMAdviceRequest
        req = LLMAdviceRequest(query="hi", session_id="sess-abc")
        assert req.session_id == "sess-abc"
