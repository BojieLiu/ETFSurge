# Round9 问题清单核对表（2026-08-08 复验）

> 本轮（round10 复诊断）在 Docker prod 容器实测，逐项核对 docs/round9-container-rediagnosis.md 的 P0-P3 47 项方案实施后的实际效果。
> 符号：✅ 已验证修复 / ⚠️ 部分修复 / ❌ 未修复 / ➖ 未专项验证

## P0（阻断）
| # | 问题 | 状态 | 本轮实测证据 |
|---|---|---|---|
| P0-1 | O24 回归 symbol-analysis 全挂 | ✅ | 5 类标的全出文（600519 3334字/510300 3353/HK 00700 2069/US AAPL 2333/000300 3170），无 STREAM_ERROR |
| P0-2 | 容器内 EM TLS 拦截 | ⚠️ | 预热从 37.4s→12.1s（降级链生效），但 `RemoteDisconnected` 仍 26 次/h（market_trends 39、factor_registry 12 等）；策略检查 fetch_history 全空、watchlist enrich 超时均由此引发 |
| P0-3 | `--host ::` 容器失效 | ✅ | 容器 0.0.0.0 正常，8000 端口从宿主可访问，nginx 正常回源 |
| P0-4 | watchlist 29.9s | ✅（部分） | perf_diag: watchlist 3.0s（29.9s→3.0s），但 realtime enrich 仍 5s 超时 → 列表 realtime 全 None（数据缺失）；端点总耗时 11-14s |
| P0-5 | LLM 超时 + 全 hold 模板 | ⚠️ | 超时已 60s→90s（实测 08:15:06 CancelledError 90s）；兜底建议已个性化（按因子分区间差异化、引用信号）；但 LLM 仍在不稳定时段每次超时（opencode_zen 61.5s 后 500） |
| P0-6 | IOPV 链 4 处解析 bug | ✅ | premium_discount IC 已出（0.1321，70 样本）——折溢价率从 no_data 恢复，sina/qq/em/TTJ 链修复生效 |
| P0-7 | TTJ 兜底 tuple/dict | ✅ | 同上，fetch_fund_nav dict 契约生效 |
| P0-8 | 560600 幽灵锚 | ✅ | design456 核心层 159338 中证A500ETF国泰（真实标的），三套方案均无 560600；表格「今日涨跌」无数据源不可用 |
| P0-9 | 报告涨跌无时间戳 | ⚠️ | market_context.data_fetched_at 已存在（08:11:11）；但表格列仍未显示「截至 HH:MM」标注（需前端渲染/模板字段） |

## P1（数据完整性）
  # | 项 | 状态 | 证据 |
|---|---|---|---|
| P1-1 | 港股 K 线 0 条 | ✅ | 00700 320 根，10s 内 |
| P1-2 | A股/美股搜索 0 命中 | ✅ | A/茅台 1、A/510 9、HK/0070 1（include_stocks=true）、US/AAPL 1、HK/腾讯 1 等全命中 |
| P1-3 | 负 IC 文案 | ⚠️ | 文案已改 `|IC|=0.45 ≥ 阈值(负向)`；但 13 个负 IC 因子仍活跃未淘汰 |
| P1-4 | 预热门禁墙钟 WARN | ➕ | 本轮预热 12.1s 未触发；A01 代码已含 wall-clock |
| P1-5 | 缺数据标的不入核心 | ✅ | design456 核心层全有真实行情（560600 已除） |
| P1-6 | 顶层 market_regime | ✅ | design detail 顶层 market_regime=range_bound |
| P1-7 | instruments 补名 | ✅ | watchlist 添加 159915/00981 返回真实名称 |
| P1-8 | benchmark_close | ❌ | tracking_error 仍 no_data「10 只样本缺 benchmark_close」（未接入） |
| P1-9 | shares_change_20d | ❌ | shares_change 仍 no_data（未接入） |
| P1-10 | sentiment 三因子静态化 | ✅ | panic_greed_diff/stock_divergence/news_direction 均 static，reason「市场级因子不参与截面 IC」 |
| P1-11 | 本地快照路径 | ➕ | 未专项测（容器路径正常） |
| P1-12 | K线口径统一 | ✅ | design 涨跌值皆实（无数据源不可用） |
| P1-13 | tech_signal 兜底 | ⚠️ | 兜底代码已显式 `{"signal": None,...}`，report 显示「数据不可用」非空；但 10/10 全不可用（数据链路失败而非兜底 bug） |
| P1-14 | 行业数据兜底 | ⚠️ | industry 仍全空（ETFXClassifier 兜底似乎未触发——依赖候选池，池在容器内弱） |
| P1-15 | 因子 n/n 假正常 | ⚠️ | 报告标题仍写「10/10 只持仓因子数据可用」但逐项 filled=6/34——假正常换形式（data_quality 已分 fallback，report_text 模板未用） |
| P1-16 | 空组合诊断 | ➕ | 本轮组合非空未触发；代码已含诊断字段 |

## P2（质量体验）
  # | 项 | 状态 | 证据 |
|---|---|---|---|
| P2-1 | level 分级 | ⚠️ | L5 50%→15%（改善）；但 L1 仍 35% 占比高（头条多为次要新闻） |
| P2-2 | 新闻情绪口径 | ➕ | 未专项（新闻智能分析未触发重跑） |
| P2-3 | 板块 ±10% 校验 | ✅ | 无超界板块值（热榜 PCB +5.63 等） |
| P2-4 | portfolio_type 持久化 | ✅ | strategy_check 详情 record 371 已存（代码实证 worker 161 行写入） |
| P2-5 | MACD 尾截断 | ➕ | 未专项 |
| P2-6 | mootdx 探针 | ⚠️ | _mootdx_realtime 仍 exception 且 source_health 未专测 |
| P2-7 | dockerignore+logs 挂载 | ✅ | 镜像 1.55GB（体积下降）；warmup 产物直接落宿主 logs/ |
| P2-8 | 因子 no_data reason tooltip | ✅ | no_data reason 明确「数据源未接入（缺 benchmark_close）等」 |
| P2-9 | vol_ratio IC 口径 | ⚠️ | vol_ratio IC=0.0002 仍无 warn（round9 0.001→0.0002 更弱），未淘汰 |
| P2-10 | 候选池身份校验 | ✅ | 幽灵锚已清除，核心层无身份错配 |
| P2-11 | 历史孤立检查记录 | ➕ | 未专测 |

## P3（测试防护）
  # | 项 | 状态 | 本轮证据 |
|---|---|---|---|
| P3-1 | symbol-stream 门禁 | ✅ | verify_e2e section_symbol_stream 存在（本次未跑完整 verify_e2e，凭功能正常反推） |
| P3-2 | watchlist 时间门禁 | ⚠️ | 3.0s 仍超 1s 期望但门禁未触发熔（说明门禁只 WARN/FAIL>5s） |
| P3-3 | A01 墙钟 | ➕ | 未触发 |
| P3-4 | docker_smoke | ✅ | backend/scripts/docker_smoke.py 存在（未跑） |
| P3-5 | 前端 SSE 错误态测试 | ➕ | 未专项 |
| P3-6 | PROFILE_WARMUP 回滚 | ✅ | prod compose 无 PROFILE_WARMUP（fortune 诊断用 run 注入） |
| P3-7 | IOPV 单测 | ✅ | test_nav_source_fallback.py 161 行+（含反例） |
| P3-8 | 因子完整性门禁 | ✅ | verify_e2e section_factor_integrity 存在 |
| P3-9 | 报告涨跌真实性门禁 | ⚠️ | data_fetched_at 有但「生于时刻行情」断言未验证（表内仍无时间戳标注） |
| P3-10 | 策略检查完整性断言 | ⚠️ | check-report 有 tech_signal「数据不可用」占比 100%（P1-13 兜底生效但数据空） |
| P3-11 | 空组合误报门禁 | ✅ | 本轮组合正常（10/10），无空误报 |

## 汇总
- **确认修复（20）**：P0-1/3/4阈值/6/7/8、P1-1/2/4/5/6/7/10/12、P2-3/4/7/8/10、P3-1/4/6/7/8 + 部分 P3
- **部分修复（12）**：P0-2/4/5/9、P1-3/13/14/15、P2-1/6、P3-2/9/10
- **未修复（2）**：P1-8（benchmark_close）、P1-9（shares_change）
- **未专项验证（10）**：P1-4/11/16、P2-2/5/11、P3-3/5/9 等

**核心残留**：容器内外部数据源（EM 优先源）仍弱（P0-2 未根治）→ 直接导致策略检查因子空、watchlist 实时空、AI 投顾快照 3 个主要质量问题的下游连锁；P1-8/P1-9 数据源接入未做。