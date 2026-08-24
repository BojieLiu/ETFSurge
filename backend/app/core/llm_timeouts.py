"""LLM 超时常量唯一事实源（round35 §19 GapE 收敛）。

收敛前散落三处：
- config.py        llm_primary_timeout=20 / llm_fallback_timeout=45（provider 级整请求默认）
- reports.py:621   httpx.Timeout(connect=60, read=90,  write=15, pool=15) 策略检查路径
- reports.py:845   httpx.Timeout(connect=60, read=120, write=15, pool=15) 设计报告路径

语义注记（归一依据，实测锚定）：
- provider 级 20/45s：Zen 免费层短生成预期 / DeepSeek 兜底放宽；env 可覆盖。
- connect=60s：R57/R70b——DeepSeek 慢连接/慢首字节实测 34-78s，两条长生成路径
  已各自实测对齐到同一上沿 60s，属同族常量。
- write/pool=15s：请求体小、池获取快，两处一致。
- read 按路径预算分化：策略检查 90s（外层完整档 180s，max_retries=0 最坏
  2×connect60=120s ≤ 180s）；设计报告 120s（9613 字实测 >46s）。

本模块只依赖 httpx，不 import app.config —— 可被 config.py 安全引用（无循环导入）。
"""

from __future__ import annotations

import httpx

# ── provider 级整请求默认超时（config.py 默认值单源；env 可覆盖）──
LLM_PROVIDER_PRIMARY_TIMEOUT_S = 20   # Zen 免费层：短生成预期
LLM_PROVIDER_FALLBACK_TIMEOUT_S = 45  # DeepSeek 官方兜底：放宽

# ── 长生成路径 httpx.Timeout 共享分量 ──
LLM_HTTP_CONNECT_S = 60.0  # R57/R70b: 慢连接实测上沿
LLM_HTTP_WRITE_S = 15.0
LLM_HTTP_POOL_S = 15.0

# ── read 按路径预算（调用方以命名常量传入，禁就地字面量）──
STRATEGY_CHECK_READ_S = 90.0    # 策略检查：外层完整档 180s 预算内（max_retries=0）
DESIGN_REPORT_READ_S = 120.0    # 设计报告：9613 字实测 >46s，120s 容纳长生成


def llm_http_timeout(read_s: float) -> httpx.Timeout:
    """构造长生成路径的 httpx.Timeout：connect/write/pool 用共享收敛值。

    read 由调用方传路径预算常量（STRATEGY_CHECK_READ_S / DESIGN_REPORT_READ_S），
    新增长生成路径时在此登记新预算常量而非再写一份四元组字面量。
    """
    return httpx.Timeout(
        connect=LLM_HTTP_CONNECT_S,
        read=read_s,
        write=LLM_HTTP_WRITE_S,
        pool=LLM_HTTP_POOL_S,
    )
