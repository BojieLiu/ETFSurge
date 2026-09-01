# v7 P2 追加：DeepSeek Harness（dsh）对照实测结论

> 2026-08-31 探针 + 实测。与 `v7-p1.5-langgraph-comparison.md` 并列——
> LangGraph 回答"编排层框架 vs 手搓"，本篇回答"**宿主平台 vs 嵌入式循环**"。

## 甄别（第一步，差点踩坑）

| 对象 | 结论 |
|---|---|
| PyPI `deepseek-harness`（作者 HenryZ838978） | ❌ **蹭名第三方包**（自称 "client for V4-Pro/Flash"），非官方，不能装 |
| `github.com/deepseek-ai/deepseek-harness` | ✅ 官方（MIT，206k+ stars，TypeScript 为主） |

## 官方形态（developer preview 0.1.1-rc.2）

- `dsh` CLI：Node/npx 分发（`npx @deepseek-ai/dsh web|tui|headless`），profile 化，
  Cordis "一切皆插件" 架构（论文 arxiv:2608.25512）。
- **Python SDK**（`deepseek-harness-sdk`）存在但 **runtime wheel 无 Windows 版**
  （仅 linux x86_64/arm64 + macOS arm64）——本机 Windows/amd64 不可进程内嵌。
- MCP 接入：Cordis overlay（`--patch xxx.cordis.yml`）插
  `@deepseek-ai/dsh-mcp-client` 行，工具暴露为 `mcp__<serverName>__<tool>`。

## 实测记录（Windows/amd64，Node 24.15.0，dsh 0.1.1-rc.2）

1. **CLI 安装**：`npx --yes @deepseek-ai/dsh --version` → `0.1.1-rc.2`（首次下载 >15min，后续快）。
2. **Overlay 解析**：`--dump-config --patch etfsurge-quote.cordis.yml` →
   `etfsurge-quote-mcp` 插件行进入 composed profile tree ✅
3. **端到端 headless**：`--profile headless --patch ... "Call the tool
   mcp__etfsurge_quote__get_realtime_quote ..."` →
   模型真实调用 MCP 工具，返回 price **4.672**（与 hub 直连实测 4.675 同源同量级，
   非编造），信封 `source: market_data_hub` ✅

overlay 内容（要点）：`command: python, args: [-m, app.mcp_servers.quote_server],
cwd: <backend>, env: {PYTHONPATH: <backend>}`——**零改后端代码**，
P0 的 stdio server 被第三方宿主直接消费。

## 对照结论（宿主平台 vs 嵌入式循环）

| 维度 | P1 嵌入式（FastAPI 进程内） | dsh 宿主平台 |
|---|---|---|
| 生命周期 | 与后端同进程（lifespan 管理） | 独立进程/CLI，session 持久化（JSONL） |
| 护栏 | 业务级（步级时间预算/循环检测/白名单/写确认/输出校验） | 平台级（插件沙箱/fs-sandbox），业务护栏由模型行为+工具描述承担 |
| MCP 消费 | 进程内 handler 直调 | 标准协议跨进程（stdio/HTTP） |
| Windows 支持 | ✅（纯 Python） | ⚠️ CLI 可用；Python SDK 无 wheel |
| 适用场景 | 生产服务内嵌、低延迟、强护栏 | 独立工作台、人工交互、跨工具聚合 |

**M+N 卖点验证**：P0 server 未改一行即被第三方宿主发现并调用——P0 设计的
"任意 MCP Host 可移植性"得到实证。

## 选型建议

- **不引入生产**：dsh 是 developer preview（breaking changes 预告中）、
  Windows SDK 缺失、业务护栏在宿主侧需重做。P1 嵌入式仍为主实现。
- **保留价值**：① P0 MCP 可移植性的第三方实证（面试可用 dsh 截图+实测对话）；
  ② 未来如做"人工工作台"，dsh + 我们的 MCP server 是现成组合。
- **实验产物位置**：overlay yml 在本机 temp（不入库）；结论以本笔记为准。

## 遗留 / 后续

- Windows Python SDK wheel 缺失——Linux 容器内可试 SDK 路径（如需）。
- 只验证了 quote_server；factor/portfolio/news server 接法相同（改 serverName/command）。
- dsh 版本迭代快（rc），overlay 格式可能变——以官方 mcp-memory.md 示例为锚。
