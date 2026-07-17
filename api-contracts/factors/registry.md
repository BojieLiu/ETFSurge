# Factor Registry API / 因子注册表 API

## 1. 概述 / Overview

**功能**: 提供因子注册、计算、IC 跟踪的统一入口。加载 `factor_definitions.yaml`，计算 30 个核心因子，支持日频 IC 跟踪。

**触发场景**: 
- 设计方案生成时自动调用因子计算管线
- 定时任务按日频率刷新因子值和 IC 序列

---

## 2. 内部接口 / Internal Interface

### 2.1 FactorRegistry

```python
class FactorRegistry:
    """因子注册表：加载 YAML → 管理因子定义 → 计算因子值"""

    def load_definitions(self, yaml_path: str = "factor_definitions.yaml") -> None:
        """加载 YAML 定义到注册表"""

    def list_factors(self, category: str | None = None) -> list[FactorDefinition]:
        """列出全部或某类因子"""

    def get_factor(self, code: str) -> FactorDefinition | None:
        """按唯一编码查询因子"""

    async def compute(self, symbols: list[str], codes: list[str] | None = None) -> dict[str, dict[str, float]]:
        """批量计算因子值，返回 {symbol: {factor_code: value}}"""
```

### 2.2 ICTracker

```python
class ICTracker:
    """IC 跟踪器：计算因子 IC / ICIR / 半衰期"""

    async def compute_ic(self, factor_values: pd.DataFrame, forward_returns: pd.Series) -> float:
        """计算单期 IC（Spearman Rank Correlation）"""

    async def compute_ic_series(self, factor_values: pd.DataFrame, forward_returns: pd.DataFrame) -> pd.Series:
        """计算多期 IC 序列"""

    async def compute_icir(self, ic_series: pd.Series) -> float:
        """计算 ICIR = mean(IC) / std(IC)"""
```

---

## 3. 数据流 / Data Flow

```
fetch_realtime_prices()        factor_definitions.yaml
         │                              │
         ▼                              ▼
    raw OHLCV data              FactorRegistry.load()
         │                              │
         └──────────┬───────────────────┘
                    ▼
          FactorEngine.compute()
                    │
                    ▼
         {symbol: {factor_code: value}}
                    │
                    ▼
             ICTracker.compute_ic()
                    │
                    ▼
             {factor_code: {ic, icir, half_life}}
```

---

## 4. Frontend-Backend Checklist

- [ ] FactorRegistry 能加载全部 167 个因子的 YAML 定义
- [ ] S1 阶段能计算 30 个核心因子
- [ ] 因子值缓存支持 TTL
- [ ] ICTracker 能计算 Spearman IC
- [ ] 全部单元测试通过（外部数据源 mock）
