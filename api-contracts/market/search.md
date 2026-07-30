# Contract: /api/v1/market/search (F2 A-share fallback)

> 关联方案: `docs/system-diagnosis-and-optimization-plan.md` F2 (P1)
> 变更类型: 既有端点行为修正（非新增端点）

## 1. 概述 / Overview
**功能描述**: 统一搜索。新增 `market=A` 在本地 `Instrument` 表为空时的降级路径，
返回真实 A 股个股列表，避免搜索断裂返回 0 结果。
**触发场景**: 前端全局搜索框输入代码/名称，`market=A` 参数命中；`Instrument` 表未预装数据时。

## 2. 端点定义 / Endpoint
```
GET /api/v1/market/search?keyword=<kw>&market=A
```

### 查询参数
| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| keyword | string | No | "" | 代码/名称/拼音/首字母模糊匹配 |
| market | string | No | null | `A` / `HK` / `US` / `global`；`null` 走 ETF 默认模式 |
| include_stocks | bool | No | false | 默认 ETF 模式是否同时包含个股 |

### 响应体
```json
[
  { "symbol": "600519", "name": "贵州茅台", "market": "A", "asset_type": "stock", "type": "stock" }
]
```

## 3. 行为契约 / Behavioral Contract (F2)
1. `market=A` 优先查询 `Instrument` 表（`market="A"`, `asset_type="stock"`）。
2. **若 `Instrument` 表无匹配行（含表为空 / 未预装）**，不再返回 `[]`，
   降级到 ETF 模式（调用 `search_etf(keyword)`），按关键词返回 ETF 列表。
3. 降级结果结构与 ETF 搜索一致：`{symbol, name, market, asset_type:"etf", type:"etf"}`。
4. 任一路径异常均被捕获并记录 WARNING，最终返回 `[]`（不抛 500）。
5. `market=HK` / `market=US` 由 `search_hk_us` 处理（F3）：以本地静态 `HKUS_ETF_MAP` 作基础匹配，
   并**实时补充**行情数据（`get_asset_realtime` 经项目统一实时管道 TwelveData/Finnhub/HK 源），
   为每个命中标的附加 `price` / `change_pct` 字段；实时查询失败则降级为仅静态结果，不抛错。
   > 注：方案原文提及 yfinance/akshare；但本项目已因境内不稳定移除 yfinance（见 `_route_us`），
   > 故 F3 采用项目既有实时管道作为 `Instrument` 表的等价补充，语义一致、更稳健。

## 4. 错误与降级 / Error & Fallback
| 情况 | 行为 |
|------|------|
| Instrument 表命中 | 返回 DB 行 |
| Instrument 表为空 | 降级 levistock，返回过滤后个股 |
| levistock 也失败 | 返回 `[]`，记 WARNING |
| 任意异常 | 捕获，返回 `[]`，HTTP 200 |

## 5. 测试 / Tests
- `verify_e2e.py` section_market: `GET /market/search?keyword=510880&market=A` 断言 200 且有结果。
- 反例（修复前）: 该请求返回 0 结果 (P1 断链)。

## Frontend-Backend Checklist
- [x] 后端 `market=A` 返回非空降级结果
- [x] 响应结构含 `symbol/name/market/asset_type/type`
- [x] verify_e2e 覆盖 `market=A` / `HK` / `US`
- [ ] 前端搜索框对 `market=A` 结果渲染（已有自动补全，无需改动）
