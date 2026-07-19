# Factor Integration Contract — Policy Factors / 政策因子契约

## 1. Added Compute Functions

### `_compute_five_year_plan(data: dict) -> float`

Returns a score 0~1 based on the ETF industry's alignment with 十五五 priorities.

**Input**: `data.get("industry")` — string from etf_classifier (e.g. "半导体", "计算机")
**Output**: float 0~1 (1.0 = highest priority, 0.3 = not a priority)
**Data source**: Static mapping table (`_POLICY_ALIGNMENT`), no external API.

### `_compute_strategic_emerging(data: dict) -> float`

Returns 1.0 if the ETF's industry is in the 战略新兴产业 directory, else 0.0.

**Input**: `data.get("industry")` 
**Output**: 1.0 or 0.0
**Data source**: Static set (`_STRATEGIC_EMERGING_INDUSTRIES`), no external API.

### `_compute_dual_circulation(data: dict) -> float`

Returns 1.0 if the ETF participates in dual-circulation (内循环/外循环) sectors.

**Input**: `data.get("industry")` or `data.get("concepts", [])`
**Output**: 1.0 or 0.0
**Data source**: Static set (`_DUAL_CIRCULATION_INDUSTRIES`), no external API.

## 2. Mappings

### 十五五 Policy Alignment Scores
```
半导体: 0.95, 计算机: 0.85, 电力设备: 0.85,
通信: 0.80, 国防军工: 0.90, 医药生物: 0.75,
汽车: 0.75, 食品饮料: 0.30, 家用电器: 0.45,
有色金属: 0.55, 银行: 0.25, 非银金融: 0.35,
交通运输: 0.50, 房地产: 0.20, 建筑装饰: 0.55,
基础化工: 0.50, 机械设备: 0.60, 电子: 0.90,
计算机: 0.80, 传媒: 0.45, 商贸零售: 0.35,
医药生物: 0.75, 宽基指数: 0.50, (fallback: 0.30)
```

### Strategic Emerging Industries
```
半导体, 电子, 计算机, 电力设备, 医药生物, 国防军工, 通信, 机械设备, 汽车
```

### Dual Circulation Beneficiaries
```
食品饮料, 家用电器, 汽车, 医药生物, 商贸零售
```
