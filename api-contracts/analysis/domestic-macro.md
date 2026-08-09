## 国内宏观/流动性数据（R5-2-10）

> **用途**: llm-report/设计报告/策略检查/投顾的 `domestic_macro` 上下文段（仅 `market="A"` 注入）。
> 数据来自 akshare 宏观接口（LPR / 中美国债收益率 / M0-M2 货币供应 / CPI-PPI / **PMI / GDP**），
> 带 24h 成功缓存 + 1h 失败缓存（R4-26 模式）；源不可用/数据滞后显式标注，不静默。
> round13 §3.1：新增 `pmi_gdp`（PMI/GDP 实测值）与 `macro_snapshot`（方向标注 -1/0/+1）两段。

### 字段结构（可空对象，HK/US 省略）

```json
{
  "domestic_macro": {
    "lpr": { "lpr_1y": 3.0, "lpr_5y": 3.5, "date": "2026-07-20", "stale": false, "note": "" },
    "bond_yields": { "cn_10y": 1.71, "us_10y": 4.75, "spread_bp": -304, "date": "2026-07-31", "stale": false, "note": "" },
    "money_supply": { "m0_yoy": 3.5, "m1_yoy": 1.2, "m2_yoy": 6.8, "date": "2026-06", "stale": false, "note": "" },
    "cpi_ppi": { "cpi_yoy": 0.2, "ppi_yoy": -2.1, "date": "2026-06", "stale": true, "note": "数据滞后至2026-06（数据源），仅作趋势参考" },
    "pmi_gdp": { "pmi_value": 49.5, "gdp_yoy": 5.2, "as_of": "2026-06", "note": "" },
    "macro_snapshot": {
      "m2_yoy_now": 6.8, "m2_yoy_3m_ago": 7.0, "m2_slope": -0.2, "m2_direction": -1,
      "pmi_value": 49.5, "pmi_direction": -1,
      "lpr_1y_now": 3.0, "lpr_1y_12m_ago": 3.45, "lpr_direction": 1,
      "macro_direction": -1, "as_of": "2026-07", "sources": ["M2", "PMI", "LPR"]
    },
    "unavailable": false
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `domestic_macro` | object/null | A 股上下文注入；HK/US 省略该键 |
| `domestic_macro.unavailable` | bool | 六源（LPR/债券/M2/CPI/PMI/GDP）全失败 = true（LLM 显式写"宏观数据源不可用"） |
| `lpr/bond_yields/money_supply/cpi_ppi` | object/null | 各子源数据；失败为 null |
| `pmi_gdp` | object/null | round13 新增：PMI 最新值 + GDP 同比（`macro_china_pmi_yearly` / `macro_china_gdp_yearly`）；失败为 null |
| `macro_snapshot` | object/null | round13 新增：M2/PMI/LPR 方向标注（-1/0/+1）+ `macro_direction` 聚合（详见 `market/macro-regime.md` §2.2） |
| `*.stale` | bool | CPI/PPI 今值 nan 或日期 >3 个月 = true |
| `*.note` | string | stale 时说明滞后原因，否则空串 |
| `bond_yields.spread_bp` | number | 中美 10Y 利差（bp） |

### 契约检查表

- [x] `market="A"` → context 含 `domestic_macro`
- [x] `market="HK"/"US"` → 无 `domestic_macro` 键
- [x] 六源全失败 → `domestic_macro.unavailable == true`
- [x] CPI/PPI 滞后 >3 个月 → `cpi_ppi.stale == true` + note
- [x] round13: `pmi_gdp` 含 PMI/GDP 真实值（非占位）；失败为 null
- [x] round13: `macro_snapshot` 含方向标注（-1/0/+1）+ `macro_direction`
- [x] 前端不消费该段（LLM 上下文内部字段，无 UI 契约）
