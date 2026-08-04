# 根因分析完整版

## 发现过程

1. **Batch test（单测 `_fetch_market_data`）** 22s 完成 → 第一次结论：问题不在 fetcher
2. **`reg.compute(symbols)` 超时** 但手拆同样步骤只要 0.4s → 结论：问题不在 post-processing
3. **`reg.compute(symbols, market_data=预获取)` 依然超时** → 结论：不是这行代码的问题
4. **faulthandler 8s 堆栈 dump** 最终找到根因：

## 根因链

```
reg.compute(symbols)
  └─ _fetch_market_data(symbols)
        └─ asyncio.gather(*tasks)            ← 无整体超时
              │
              ├─ fetch_one(sym=520520) → run_sync → thread_pool
              │    └─ fetch_history('520520', 'A', 'daily')
              │          └─ _is_etf_code('520520') → False (52xxx前缀不在ETF白名单)
              │                └─ _mootdx_history('520520')
              │                      └─ client.bars(...)    ← TCP socket 读操作
              │                            └─ tdxpy._call_api
              │                                  └─ socket.recv()  ← 无读超时! ∞ 阻塞
              │                                                    thread一直不释放
              │
              ├─ 同理: fetch_one(sym=520570) → thread stuck
              ├─ 同理: fetch_one(sym=520590) → thread stuck
              │
              ├─ 重复...线程池(12 workers)被耗尽
              │  thread_pool: [stuck_mootdx, stuck_mootdx, stuck_mootdx, ...]
              │
              └─ 新的 run_sync 调用排队等待线程
                 queue_depth > 16 → "POOL SATURATION!" 日志可见
                    │
                    ▼
                 asyncio.gather 永远等待剩余任务
                 asyncio.wait_for(timeout=60) 无法中断
                 因为 event loop 在 Windows IOCP 上等待 I/O
                 → 进程卡死在 asyncio.run() 里
```

## 直接原因

| 层 | 问题 |
|----|------|
| `factor_registry.py:832` | `asyncio.gather(*tasks)` **无整体超时保护** |
| `china_market.py:104-105` | `_mootdx_history` → `client.bars()` **TCP socket 读操作无超时** |
| `china_market.py:60-75` | `_mootdx_client` 全局单例，**线程不安全**导致多线程共享 socket 冲突 |
| `china_market.py:52` | `_is_etf_code()` 的 `_ETF_PREFIXES` **缺少 "52" 前缀**（港股通ETF） |

## 为什么纯 `_fetch_market_data` 测试能过？

因为`run_sync(fetch_history, ..., timeout=20)` 中的 **20s 超时是 `asyncio.wait_for` 的超时**，它 cancels 的是 asyncio 层面的 Future，**不是** thread pool 里的线程。线程里的 mootdx socket 读操作继续跑。在轻负载测试中，这些 mootdx 调用碰巧在 20s 内返回了。但在有背景负载（sentiment 模块也占线程）的情况下，12 线程的池很快被耗尽，新来的 `run_sync` 排长队，而 asyncio.gather 等待全部完成。
