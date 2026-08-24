"""round35 §11-T-② (docs/round35-architecture-review.md §11.5) —
WS 推送背压统一验证：僵死客户端 5s 超时摘除，不阻塞广播循环与正常客户端。

负向用例对旧实现必红：裸 ``await send_text()`` 遇到永挂起的客户端会永久阻塞，
正常端收不到消息、广播不返回。

（round35 RC-D3③-b: DesignReportManager 的 WS 会话/broadcast 已随
/ws/design-report 端点删除，其用例同步移除；TaskNotifyManager 背压契约保留。）
"""
import asyncio
import time

import pytest

from app.tasks.task_manager import TaskNotifyManager


class FakeWS:
    """可编程行为的伪 WS：behavior='ok' 立即发送；'hang' 永挂起；'error' 抛错。"""

    def __init__(self, behavior: str = "ok"):
        self.behavior = behavior
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        if self.behavior == "hang":
            await asyncio.sleep(3600)
        if self.behavior == "error":
            raise RuntimeError("connection closed")
        self.sent.append(payload)


@pytest.mark.asyncio
async def test_task_notify_slow_client_does_not_block_broadcast():
    """负向：一个 send_text 永挂起 + 一个正常客户端 → 正常端仍收到消息、
    僵死端被摘除、广播总耗时 ≈5s 封顶（旧裸 await 实现会永久阻塞——必红）。"""
    mgr = TaskNotifyManager()
    healthy = FakeWS("ok")
    stuck = FakeWS("hang")
    mgr.register(stuck)
    mgr.register(healthy)

    t0 = time.monotonic()
    await asyncio.wait_for(mgr.broadcast({"type": "stage", "n": 1}), timeout=15.0)
    elapsed = time.monotonic() - t0

    assert any('"n": 1' in s or '"n":1' in s for s in healthy.sent), "健康客户端必须收到消息"
    assert stuck not in mgr._connections, "僵死客户端必须被摘除"
    assert 4.0 <= elapsed < 8.0, f"广播应被 5s 背压封顶，实际 {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_all_healthy_clients_receive_in_order():
    """正向：全健康客户端均收到且顺序一致。"""
    mgr = TaskNotifyManager()
    clients = [FakeWS("ok") for _ in range(3)]
    for c in clients:
        mgr.register(c)

    for i in range(4):
        await mgr.broadcast({"type": "tick", "i": i})

    for c in clients:
        assert len(c.sent) == 4
        # 各客户端收到的序列彼此一致（广播顺序一致）
        assert c.sent == clients[0].sent


@pytest.mark.asyncio
async def test_error_client_removed_without_affecting_others():
    """send_text 抛错的客户端同样被摘除（既有语义保持）。"""
    mgr = TaskNotifyManager()
    bad = FakeWS("error")
    good = FakeWS("ok")
    mgr.register(bad)
    mgr.register(good)

    await mgr.broadcast({"type": "x"})

    assert bad not in mgr._connections
    assert good.sent and bad not in mgr._connections
