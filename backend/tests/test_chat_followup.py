"""A+B 追问会话护栏：类型隔离 + 冻结快照 + 无效 id（先失败后实现，已绿）。"""
from app.services.chat_session import ChatSessionStore


def test_type_mismatch_opens_new():
    s = ChatSessionStore(capacity=10)
    sid, _ = s.start_or_get(None, expect_type="report")
    s.append(sid, {"role": "user", "content": "首报"})
    sid2, hist2 = s.start_or_get(sid, expect_type="symbol")
    assert sid2 != sid
    assert hist2 == []


def test_frozen_snapshot_roundtrip():
    s = ChatSessionStore(capacity=10)
    sid, _ = s.start_or_get(None, expect_type="symbol")
    s.set_frozen(sid, {"snapshot_text": "510300 快照", "symbol": "510300"}, market="A", symbol="510300")
    assert s.get_frozen(sid)["symbol"] == "510300"


def test_invalid_id_opens_new_without_error():
    s = ChatSessionStore(capacity=10)
    sid, hist = s.start_or_get("sess-does-not-exist", expect_type="report")
    assert sid.startswith("sess-")
    assert hist == []
