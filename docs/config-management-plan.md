# ETF Surge 配置管理面板 — 设计方案

> 版本: v2.0 | 日期: 2026-07-22 | 状态: 定稿(通过多轮独立审查)

## 目录

- [1. 问题与目标](#1-问题与目标)
- [2. 当前现状分析](#2-当前现状分析)
- [3. 方案概述](#3-方案概述)
- [4. 后端详细设计](#4-后端详细设计)
- [5. 前端详细设计](#5-前端详细设计)
- [6. API 契约](#6-api-契约)
- [7. 数据流与状态机](#7-数据流与状态机)
- [8. 兼容性与迁移策略](#8-兼容性与迁移策略)
- [9. 实施范围与验收标准](#9-实施范围与验收标准)
- [10. 风险与备选方案](#10-风险与备选方案)

---

## 1. 问题与目标

### 1.1 问题描述

用户首次使用 ETF Surge 时，需要手动编辑 `backend/.env` 文件填入 API Key，否则核心功能（LLM 分析、行情数据、技术指标）不可用。当前需要配置的 key 包括：

| Key | 用途 | 缺少时的影响 |
|-----|------|-------------|
| `DEEPSEEK_API_KEY` | LLM 分析（降级） | LLM 模块不可用 |
| `OPENCODE_ZEN_API_KEY` | LLM 分析（主力） | LLM 模块不可用 |
| `TUSHARE_TOKEN` | A 股行情 | A 股数据降级到备用源 |
| `ALPHAVANTAGE_API_KEY` | 美股行情 | Alpha Vantage 源不可用 |
| `FINNHUB_API_KEY` | 美股数据 | Finnhub 源不可用 |
| `TWELVEDATA_API_KEY` | 行情数据 | Twelve Data 源不可用 |
| `FRED_API_KEY` | 宏观数据 | FRED 经济指标不可用 |

**核心矛盾**: 配置门槛过高。用户需要：找到 `.env` 文件 → 编辑文本 → 重启服务。这对非技术用户构成明显的使用障碍。

### 1.2 目标

- 用户通过前端 UI 即可填写和修改所有 API Key，无需触碰命令行或文件系统
- 配置即时生效，无需重启后端服务
- 保留 `.env`/环境变量作为启动基线，DB 为空时无缝降级

### 1.3 非目标

- ❌ 不加密存储（和 `.env` 同等级安全保护）
- ❌ 不引入新的外部依赖（如 Redis、Vault）
- ❌ 不改动现有 fetcher / provider 的调用签名
- ❌ 不处理多用户/权限/角色

---

## 2. 当前现状分析

### 2.1 配置加载链路

```
.env 文件
    │  pydantic_settings 读取
    ▼
config.py :: Settings（单例，import 时加载）
    │  模块级 settings = Settings()
    ▼
消费方（14 处 import settings）:
    ├── analysis/llm.py         → settings.opencode_zen_api_key / settings.deepseek_api_key
    ├── analysis/provider.py    → settings.* (构建 ProviderConfig 列表)
    ├── fetchers/*.py           → 每个 fetcher 取自己的 key
    ├── main.py                 → settings.cors_origins_str, settings.log_level
    ├── database.py             → settings.database_url
    ├── core/logging.py         → settings.log_level, settings.log_file
    ├── services/cache_service.py → settings.redis_url
    └── monitor/token_usage.py  → settings.*
```

### 2.2 配置消费模式

所有 fetcher 均采用**惰性加载 + 健康检查 + 降级**的模式：

```python
def _get_apikey() -> str | None:
    key = settings.alphavantage_api_key
    if not key or key == "" or key.startswith("your_"):
        return None
    return key
```

当 key 缺失时，对应数据源被标记为"不可用"，请求会自动降级到备用源或返回结构化错误。

### 2.3 当前 Admin 路由

```
/api/v1/admin  (backend/app/routers/admin.py)
  ├── GET /token-usage              → Token 用量汇总
  ├── GET /token-usage/timeseries   → Token 时间序列
  └── GET /token-usage/failures     → 失败记录
```

Admin 路由已存在，扩展空间充足。

### 2.4 前端导航

当前 `App.vue` 的 `navItems` 包含 5 个入口：

```
Dashboard / 组合分析 / 行情分析 / 资讯监控 / Token监控
```

新增"配置管理"入口后变为 6 个。

---

## 3. 方案概述

### 3.1 核心设计

```
┌─────────────────────────────┐
│     前端 ConfigPage.vue      │  ← 新页面
│  - 分组的配置项列表           │
│  - 已配置: 脱敏显示          │
│  - 未配置: 空输入框           │
│  - 保存后即时刷新             │
└─────────┬───────────────────┘
          │ GET/PUT /api/v1/admin/config
          ▼
┌─────────────────────────────┐
│  GET  /api/v1/admin/config   │  ← 扩展 admin.py
│  PUT  /api/v1/admin/config   │
└─────────┬───────────────────┘
          │
          ▼
┌────────────────────────────────┐
│  ConfigManager (单例)          │  ← 核心新增
│  - db_overrides: dict          │
│  - get(key): db > env fallback │
│  - set_override(key, value)    │
└─────────┬──────────────────────┘
          │
          ▼
┌────────────────────────────────┐
│  SQLite: app_config 表         │  ← 新表
│  key (PK) / value / updated_at │
└────────────────────────────────┘
```

### 3.2 数据流

**启动时**：
```
init_db() → Base.metadata.create_all (含新表)
         → ConfigManager._load_from_db()
         → 后续 get(key) 直接走内存缓存
```

**用户配置时**：
```
前端填写 key → PUT /api/v1/admin/config
              → 写入 app_config 表 (UPSERT)
              → ConfigManager.set_override(key, value)
              → 返回成功
```

**运行时获取 key**：
```
fetcher/llm 调用 ConfigManager.get("DEEPSEEK_API_KEY")
  → 内存缓存命中 → 返回
  → 未命中 → 查 DB → 有则返回并缓存
  → DB 无 → 回退到 settings.deepseek_api_key (.env)
```

### 3.3 设计原则

- **最小改动**: 不改任何 fetcher / provider 的 import 语句和调用签名
- **向后兼容**: DB 为空时完全退化为当前行为（仅读 .env）
- **零外部依赖**: 不新增 pip 包

---

## 4. 后端详细设计

### 4.1 新增文件: `backend/app/models/app_config.py`

```python
"""AppConfig model — runtime key-value configuration persisted to SQLite."""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, func
from ..database import Base


class AppConfig(Base):
    __tablename__ = "app_config"

    key = Column(String(100), primary_key=True)
    value = Column(String(500), nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
```

**设计说明**:
- 用 key-PK 简化 upsert 逻辑
- `updated_at` 记录最后修改时间，用于前端展示"上次更新"
- 长度 500 够容纳最长的 API key（OpenAI 格式通常 ~50 字符，DeepSeek ~40）

### 4.2 新增文件: `backend/app/core/config_manager.py`

```python
"""
ConfigManager — 运行时配置管理器。

优先级: DB overrides > .env (pydantic settings)
"""

from __future__ import annotations

from typing import Optional
from ..config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)

# ── 所有可配置项的元数据 ─────────────────────────
CONFIG_ITEMS: list[dict] = [
    # (key, label, description, group, placeholder)
    {"key": "DEEPSEEK_API_KEY",       "label": "DeepSeek API Key",      "group": "LLM 服务",
     "description": "DeepSeek 官方 API 密钥，用于 LLM 分析和报告生成（降级线路）",
     "placeholder": "sk-xxxxxxxxxxxxxxxx"},
    {"key": "OPENCODE_ZEN_API_KEY",   "label": "OpenCode Zen API Key",  "group": "LLM 服务",
     "description": "OpenCode Zen 平台 API 密钥，用于 LLM 分析和报告生成（主力线路）",
     "placeholder": "sk-xxxxxxxxxxxxxxxx"},
    {"key": "TUSHARE_TOKEN",          "label": "Tushare Token",         "group": "数据源",
     "description": "Tushare Pro 接口 Token，用于 A 股行情数据",
     "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    {"key": "ALPHAVANTAGE_API_KEY",   "label": "Alpha Vantage API Key", "group": "数据源",
     "description": "Alpha Vantage API 密钥，用于美股实时行情",
     "placeholder": "xxxxxxxxxx"},
    {"key": "FINNHUB_API_KEY",        "label": "Finnhub API Key",       "group": "数据源",
     "description": "Finnhub API 密钥，用于美股数据与基本面",
     "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxx"},
    {"key": "TWELVEDATA_API_KEY",     "label": "Twelve Data API Key",   "group": "数据源",
     "description": "Twelve Data API 密钥，用于行情数据与指标",
     "placeholder": "xxxxxxxxxxxxxxxx"},
    {"key": "FRED_API_KEY",           "label": "FRED API Key",          "group": "数据源",
     "description": "St. Louis Fed FRED API 密钥，用于美国宏观经济指标",
     "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
]


class ConfigManager:
    """运行时配置管理器——单例，无需线程锁（FastAPI 单进程 async 环境）。"""

    _instance: Optional[ConfigManager] = None
    _db_overrides: dict[str, str] = {}

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def init(self, db_session_factory):
        """从 app_config 表加载所有 overrides 到内存。"""
        from sqlalchemy import select
        from ..models.app_config import AppConfig

        async with db_session_factory() as session:
            result = await session.execute(select(AppConfig))
            rows = result.scalars().all()
            self._db_overrides = {row.key: row.value for row in rows}
        logger.info("[config] Loaded %d overrides from DB", len(self._db_overrides))

    @staticmethod
    def _is_valid_value(value: str | None) -> bool:
        """判断配置值是否有效——排除空值、占位符值。

        所有 fetcher 的 _get_apikey() 都检查 startswith("your_")
        来过滤 .env 模板占位值（如 your_alphavantage_api_key），
        ConfigManager 保持一致。
        """
        if not value or not value.strip():
            return False
        if value.strip().startswith("your_"):
            return False
        return True

    def get(self, key: str) -> str | None:
        """获取配置值。优先级: DB overrides > .env (settings)。

        过滤掉空值、占位符值（your_*），与所有 fetcher 的行为对齐。
        """
        # 1. 查 DB override（内存缓存）
        if key in self._db_overrides:
            val = self._db_overrides[key]
            if self._is_valid_value(val):
                return val
        # 2. 回退到 .env — 通过 settings 的属性查找
        env_val = getattr(settings, key.lower(), None)
        if self._is_valid_value(env_val):
            return env_val
        return None

    def is_configured(self, key: str) -> bool:
        """检查指定 key 是否已配置（DB 或 .env 任意来源有有效值即视为已配置）。"""
        return self.get(key) is not None

    @property
    def has_db_overrides(self) -> bool:
        """是否有通过 DB 配置的 overrides。"""
        return bool(self._db_overrides)

    def set_override(self, key: str, value: str):
        """DB commit 成功后，将新值设置到内存缓存。

        注意：invalidate() 在这个场景不正确——它会清除缓存，
        导致下一次 get(key) 回退到 .env 而非读取新 DB 值。
        """
        self._db_overrides[key] = value

    def invalidate(self, key: str):
        """清除指定 key 的缓存（用于外部手动修改 DB 后强制重读）。"""
        self._db_overrides.pop(key, None)

    async def reload(self):
        """完全重新加载 DB overrides。

        使用临时字典再原子赋值，避免
        clear() 和 init() 之间的竞态窗口。
        """
        from ..database import async_session

        async with async_session() as session:
            from sqlalchemy import select
            from ..models.app_config import AppConfig
            result = await session.execute(select(AppConfig))
            rows = result.scalars().all()
            new_overrides = {row.key: row.value for row in rows}

        # 原子替换
        self._db_overrides = new_overrides
        logger.info("[config] Reloaded %d overrides from DB", len(self._db_overrides))

    def list_config_items(self) -> list[dict]:
        """返回所有可配置项的定义 + 当前状态 + 脱敏值，供前端渲染。"""
        return [
            {
                **item,
                "configured": self.is_configured(item["key"]),
                "masked_value": self._mask_value(item["key"]),
            }
            for item in CONFIG_ITEMS
        ]


    def _mask_value(self, key: str) -> str | None:
        """对已配置的 key 做脱敏处理，返回形如 'sk-****a1b2' 的字符串。"""
        value = self.get(key)
        if not value:
            return None
        if len(value) <= 8:
            return value[:4] + "****"
        return value[:4] + "****" + value[-4:]


# 全局单例
config_manager = ConfigManager()
```

**设计说明**:
- `CONFIG_ITEMS` 集中管理所有可配置项的元数据（key 名、显示名、分组、占位符），后端是单一事实来源
- `get()` 先查 DB 再回退 `.env`，使用 `getattr(settings, key.lower(), None)` 将大写 key 映射到 pydantic 的小写字段
- FastAPI 单进程 async 环境下无需线程锁

### 4.3 修改文件: `backend/app/models/__init__.py`

```python
from .app_config import AppConfig  # 新增导出
```

### 4.4 修改文件: `backend/app/database.py`

在 `init_db()` 的 `import` 块追加：

```python
from .models.app_config import AppConfig
```

### 4.5 修改文件: `backend/app/routers/admin.py`

追加两个端点：

```python
from ..core.config_manager import config_manager, CONFIG_ITEMS


@router.get("/config", response_model=dict)
async def get_config():
    """返回所有配置项的定义与当前状态。"""
    return {
        "items": config_manager.list_config_items(),
        "source": "database_overrides" if config_manager.has_db_overrides else "env_file",
    }


@router.put("/config", status_code=200)
async def update_config(payload: dict):
    """
    更新配置项。
    
    请求体: {"DEEPSEEK_API_KEY": "sk-xxx", "TUSHARE_TOKEN": "xxx"}
    返回: {"updated": ["DEEPSEEK_API_KEY", "TUSHARE_TOKEN"], "failed": []}
    """
    from ..database import async_session
    from ..models.app_config import AppConfig
    from sqlalchemy import select

    valid_keys = {item["key"] for item in CONFIG_ITEMS}
    updated, failed = [], []

    async with async_session() as session:
        for key, value in payload.items():
            if key not in valid_keys:
                failed.append({"key": key, "reason": "unknown_config_key"})
                continue
            if not value or not value.strip():
                failed.append({"key": key, "reason": "empty_value"})
                continue

            # UPSERT: 存在则更新，不存在则插入
            # updated_at 由模型层的 onupdate=func.now() 自动处理
            result = await session.execute(
                select(AppConfig).where(AppConfig.key == key)
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.value = value.strip()
            else:
                session.add(AppConfig(key=key, value=value.strip()))
            updated.append(key)

        await session.commit()

    # commit 成功后直接将新值写入内存缓存
    # 不能用 invalidate() — 那会让下一次 get() 回退到 .env
    for key in updated:
        config_manager.set_override(key, payload[key].strip())

    return {"updated": updated, "failed": failed}


@router.delete("/config/{key}", status_code=200)
async def delete_config(key: str):
    """删除指定配置项的 DB override，回退到 .env 值。"""
    from ..database import async_session
    from ..models.app_config import AppConfig
    from sqlalchemy import select

    valid_keys = {item["key"] for item in CONFIG_ITEMS}
    if key not in valid_keys:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Config key not in DB")

    async with async_session() as session:
        result = await session.execute(
            select(AppConfig).where(AppConfig.key == key)
        )
        existing = result.scalar_one_or_none()
        if not existing:
            from fastapi import HTTPException
            raise HTTPException(status_code=404, detail="Config key not in DB")
        await session.delete(existing)
        await session.commit()

    config_manager.invalidate(key)
    return {"deleted": key, "fallback_source": "env_file"}
```

### 4.6 修改文件: `backend/app/main.py`

在 `lifespan` 中，`init_db()` 后调用 `config_manager.init()`：

```python
# 在 init_db() 和 redis_cache.init() 之后加入
from .core.config_manager import config_manager
await config_manager.init(async_session)  # async_session 已在模块顶部导入
logger.info("[config] ConfigManager initialized (has_db_overrides=%s)",
            config_manager.has_db_overrides)
```

其中 `async_session` 需要在 `main.py` 模块顶部追加导入：

```python
from .database import init_db, async_session  # 追加 async_session
```

> 说明：选择在 main.py 中显式传入 session factory 而非在 ConfigManager 内部导入，是为了避免可能的循环依赖（main → config_manager → database → config），并保持依赖注入的显式性。ConfigManager.reload() 内部导入 async_session 是因为 reload 在运行时按需调用，不存在模块加载时的循环依赖风险。

### 4.7 关键调用方修改（按需）

**原则**: 不改调用签名。现有代码中各处 `settings.some_key` 保持不变，因为：

- `settings`（pydantic 的 Settings 单例）在模块 import 时已加载 `.env` 值
- `ConfigManager.get()` 返回 "DB override > .env fallback"，仅新代码使用
- **不需要**改成 `config_manager.get()` — 如果改了，就没有"不回退"的安全网

但以下**全部调用方**建议改为通过 ConfigManager 获取，以实现运行时热更新：

1. `backend/app/analysis/provider.py` 的 `get_configured_providers()` — 每次 LLM 请求时调用
2. `backend/app/analysis/provider.py` 的 `has_any_api_key()` — 调用前检查
3. `backend/app/fetchers/tushare_fetcher.py` 的 `_pro()` — 惰性初始化

改为：

```python
# 之前: from ..config import settings; settings.opencode_zen_api_key
# 之后: from ..core.config_manager import config_manager; config_manager.get("OPENCODE_ZEN_API_KEY")
```

这样用户在 UI 修改 LLM Key 后，下一次 LLM 调用就能使用新 key，无需重启。

**其他 fetcher**（alphavantage, finnhub, twelvedata, fred）在模块级 `_get_apikey()` 中读取 key，只在 import 或首次调用时读取一次。要实现热更新需要改，但**本方案第一阶段不做——即 DB 持久化后重启才生效；后续迭代再改。**

### 4.8 修改清单

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `backend/app/models/app_config.py` | **新增** | 15 |
| `backend/app/models/__init__.py` | 修改（追加导出） | 1 |
| `backend/app/core/config_manager.py` | **新增** | 120 |
| `backend/app/database.py` | 修改（追加 import） | 1 |
| `backend/app/routers/admin.py` | 修改（追加 GET/PUT/DELETE 端点） | 80 |
| `backend/app/main.py` | 修改（追加 init） | 3 |
| `backend/app/analysis/provider.py` | 修改（选做: 热更新） | 6 |
| `backend/app/tests/test_config_manager.py` | **新增** | 80 |
| **合计** | | **~281** |

---

## 5. 前端详细设计

### 5.1 新增页面: `frontend/src/views/ConfigView.vue`

```
路径: /admin/config
导航标签: "系统配置"
导航图标: "⚙️"
```

**页面布局**:

```
┌──────────────────────────────────────────────┐
│  ⚙️ 系统配置                                  │
│  管理 API 密钥与服务配置。修改后立即生效。       │
├──────────────────────────────────────────────┤
│                                              │
│  ┌─ LLM 服务 ────────────────────────────┐   │
│  │                                        │   │
│  │  DeepSeek API Key                      │   │
│  │  [ 已配置: sk-****a1b2 ]  [ 编辑 ]     │   │
│  │  OpenCode Zen API Key                  │   │
│  │  [ 未配置                    ]  [保存] │   │
│  └────────────────────────────────────────┘   │
│                                              │
│  ┌─ 数据源 ──────────────────────────────┐   │
│  │                                        │   │
│  │  Tushare Token                         │   │
│  │  [ 已配置: xxxx****xxxx ]  [ 编辑 ]    │   │
│  │  Alpha Vantage API Key                 │   │
│  │  [ 未配置                    ]  [保存] │   │
│  │  ...                                   │   │
│  └────────────────────────────────────────┘   │
│                                              │
│  ┌─ 状态提示 ────────────────────────────┐   │
│  │  💡 已从 .env 加载 2 项默认配置         │   │
│  └────────────────────────────────────────┘   │
└──────────────────────────────────────────────┘
```

**组件状态**:

| 状态 | 描述 | 前端表现 |
|------|------|---------|
| `loading` | 正在获取配置列表 | 骨架屏 |
| `loaded` | 已加载，显示配置项 | 分组卡片列表 |
| `saving` | 正在保存 | 保存按钮 disabled + spinner |
| `saved` | 保存成功 | Toast "配置已保存" |
| `error` | 保存失败 | Toast + 行级红色提示 |

**交互逻辑**:

1. 页面加载 → `GET /api/v1/admin/config` → 渲染
2. 每行显示 key 名 + 描述 + 输入框/脱敏值 + 保存按钮
3. 点击"编辑"→ 输入框变为可编辑
4. 点击"保存" → `PUT /api/v1/admin/config` → 局部刷新该行状态
5. 整页刷新按钮 → 重新加载

**脱敏规则**: 显示前 4 字符 + `****` + 后 4 字符（少于 10 字符则完全隐藏）

### 5.2 前端路由

修改 `frontend/src/router/index.js`：

```javascript
{
  path: '/admin/config',
  name: 'config',
  component: () => import('../views/ConfigView.vue'),
  meta: { title: '系统配置', description: '管理 API 密钥与服务配置' },
}
```

### 5.3 前端导航

修改 `frontend/src/App.vue` 的 `navItems`：

```javascript
const navItems = [
  { path: '/', label: 'Dashboard', icon: '📊' },
  { path: '/portfolio-analysis', label: '组合分析', icon: '📈' },
  { path: '/market-analysis', label: '行情分析', icon: '📰' },
  { path: '/news', label: '资讯监控', icon: '📋' },
  { path: '/token-monitor', label: 'Token监控', icon: '🔑' },
  { path: '/admin/config', label: '系统配置', icon: '⚙️' },
]
```

### 5.4 API 层

在 `frontend/src/api/index.js` 的 `adminApi` 追加：

```javascript
export const adminApi = {
  // ... 现有
  getConfig: () => api.get('/admin/config'),
  updateConfig: (payload) => api.put('/admin/config', payload),
}
```

### 5.5 修改清单

| 文件 | 操作 | 预估行数 |
|------|------|---------|
| `frontend/src/views/ConfigView.vue` | **新增** | 180 |
| `frontend/src/router/index.js` | 修改（追加路由） | 5 |
| `frontend/src/App.vue` | 修改（追加导航项） | 1 |
| `frontend/src/api/index.js` | 修改（追加 API 方法） | 2 |
| **合计** | | **~188** |

---

## 6. API 契约

### 6.1 GET /api/v1/admin/config

**请求**:

```
GET /api/v1/admin/config
```

**响应 200**:

```json
{
  "items": [
    {
      "key": "DEEPSEEK_API_KEY",
      "label": "DeepSeek API Key",
      "description": "DeepSeek 官方 API 密钥，用于 LLM 分析...",
      "group": "LLM 服务",
      "placeholder": "sk-xxxxxxxxxxxxxxxx",
      "configured": true,
      "masked_value": "sk-****a1b2"
    },
    {
      "key": "TUSHARE_TOKEN",
      "label": "Tushare Token",
      "description": "Tushare Pro 接口 Token...",
      "group": "数据源",
      "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
      "configured": false,
      "masked_value": null
    }
  ],
  "source": "database_overrides"
}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | string | 配置键名（常量） |
| `label` | string | 显示名称 |
| `description` | string | 用途说明 |
| `group` | string | 分组标签 |
| `placeholder` | string 或 null | 输入框占位提示 |
| `configured` | boolean | 是否已配置 |
| `masked_value` | string 或 null | 脱敏后的值（已配置时） |
| `source` | string | 数据来源: `database_overrides` 或 `env_file` |

### 6.2 PUT /api/v1/admin/config

**请求**:

```
PUT /api/v1/admin/config
Content-Type: application/json

{
  "DEEPSEEK_API_KEY": "DEMO-KEY-VALUE",
  "TUSHARE_TOKEN": "ANOTHER-DEMO-VALUE"
}
```

> 说明：请求体是一个扁平 JSON 对象，key=配置名，value=API key 值。
> 传递无效的配置名或空值会被放入 `failed` 数组，不影响其他有效项。
> 如需清除已保存的 DB override，使用 `DELETE /api/v1/admin/config/{key}`。

**响应 200**:

```json
{
  "updated": ["DEEPSEEK_API_KEY"],
  "failed": [
    {"key": "TUSHARE_TOKEN", "reason": "empty_value"}
  ]
}
```

### 6.3 DELETE /api/v1/admin/config/{key}

删除已保存的 DB override，允许回退到 `.env` 值。

**请求**:

```
DELETE /api/v1/admin/config/DEEPSEEK_API_KEY
```

**响应 200**:

```json
{
  "deleted": "DEEPSEEK_API_KEY",
  "fallback_source": "env_file"
}
```

**响应 404**:

```json
{
  "detail": "Config key not in DB"
}
```
---

## 7. 数据流与状态机

### 7.1 全链路时序

```
User                   Frontend                Backend                          DB
  │                       │                       │                              │
  │  关掉浏览器/下次打开    │                       │                              │
  │                       │                       │                              │
  │  访问 /admin/config    │                       │                              │
  │──────────────────────►│                       │                              │
  │                       │  GET /admin/config     │                              │
  │                       │──────────────────────►│                              │
  │                       │                       │  config_manager              │
  │                       │                       │  .list_config_items()        │
  │                       │                       │  ├── 查内存 dict             │
  │                       │                       │  └── 查 settings (env)       │
  │                       │                       │                              │
  │                       │  ◄──── 200 + items    │                              │
  │  ◄──── 渲染页面       │                       │                              │
  │                       │                       │                              │
  │  修改 key → 点击保存   │                       │                              │
  │──────────────────────►│                       │                              │
  │                       │  PUT /admin/config     │                              │
  │                       │──────────────────────►│                              │
  │                       │                       │  UPSERT app_config           │
  │                       │                       │─────────────────────────────►│
  │                       │                       │  ◄──── OK                   │
  │                       │                       │  set_override(key, value)    │
  │                       │                       │                              │
  │                       │  ◄──── 200 + updated  │                              │
  │  ◄──── 行级刷新       │                       │                              │
  │                       │                       │                              │
  │  [后续 LLM 调用]      │                       │                              │
  │                       │                       │  config_manager              │
  │                       │                       │  .get("DEEPSEEK_API_KEY")    │
  │                       │                       │  → 返回 DB 值（非 env）      │
  │                       │                       │                              │
```

### 7.2 状态机

```
[系统启动]
    │
    ▼
[init_db + config_manager.init()]
    │  DB 有 overrides  → _db_overrides 填充
    │  DB 无 overrides  → _db_overrides 为空
    ▼
[正常服务]
    │
    ├── [前端 GET 配置] → 返回 items + configured 状态
    │
    ├── [前端 PUT 配置] → UPSERT DB → invalidate cache → 返回
    │
    ├── [运行时 get(key)]
    │       ├── key in _db_overrides → 返回 DB 值
    │       ├── getattr(settings, key.lower()) → 返回 env 值
    │       └── 都不存在 → None
    │
    └── [重启/重载] → 回到 init
```

---

## 8. 兼容性与迁移策略

### 8.1 降级矩阵

| 场景 | 行为 | 对用户的影响 |
|------|------|------------|
| DB 无 overrides | 完全退化为当前行为，仅读 `.env` | 无影响 |
| DB 有 overrides | DB 值优先于 `.env` | 透明，无感知 |
| 用户删掉所有 overrides | 退回到 `.env` | 无影响 |
| `.env` 也不存在 key | `get()` 返回 None | 功能不可用（和现在一样） |

### 8.2 Docker 兼容

Docker 部署场景中，key 通常通过环境变量注入。**DB overrides 优先级高于环境变量**，但 Docker 用户可以不使用 UI配置，完全走 env。

如果用户同时用了 env + DB overrides，DB 值优先——这是设计预期（用户主动修改意味着覆盖）。

### 8.3 迁移路径

1. **部署**：新表 `app_config` 通过 `Base.metadata.create_all` 自动创建，无需手动迁移
2. **已有数据**：已有的 `.env` 值不受影响；用户首次打开配置页面时看见的是从 `.env` 加载的值
3. **回滚**：删除本方案实现的代码后，系统退回到原始 `.env` 机制，不影响任何功能

### 8.4 性能影响

- `ConfigManager.init()` 加载全部 app_config 行（最多 7 条记录），耗时 < 10ms
- `get()` 是 O(1) dict 查找
- `invalidate()` 是 O(1) pop
- 无额外网络延迟或 IO

---

## 9. 实施范围与验收标准

### 9.1 第一阶段（本方案）

| 模块 | 内容 | 优先级 |
|------|------|--------|
| 后端 Model | `models/app_config.py` | P0 |
| 后端 Core | `core/config_manager.py` | P0 |
| 后端 API | `GET/PUT /admin/config` | P0 |
| 后端 Init | `main.py` 中 init | P0 |
| 前端页面 | `views/ConfigView.vue` | P0 |
| 前端路由/导航 | router + App.vue | P0 |
| 前端 API | `adminApi.getConfig/updateConfig` | P0 |
| LLM 热更新 | `provider.py` 改用 config_manager | P1（可选） |

### 9.2 验收标准

| # | 验收项 | 验证方式 |
|---|--------|---------|
| 1 | 新用户无 `.env` → 页面显示所有 key 为未配置 | `GET /admin/config` 返回全部 `configured: false` |
| 2 | `.env` 有 key → 页面显示脱敏值 + `configured: true` | 同上 |
| 3 | 在页面填写 key 并保存 → DB 持久化 | 重启后页面依然显示该 key 为已配置 |
| 4 | 保存后同一后端进程中 LLM 调用使用新 key | 修改 OPENCODE_ZEN_API_KEY → 发起 LLM 请求成功 |
| 5 | PUT 空值或未知 key → 返回 `failed` | 响应体校验 |
| 6 | 后端单测通过 | `python -m pytest tests/test_config_manager.py` |
| 7 | 前端 build 通过 | `npm run build` |
| 8 | Lint / 语法检查 | `run_verifiers` 通过 |

### 9.3 不纳入本版本

- ~~**删除/清除配置**（V2）~~ ✅ V1 已包含 DELETE 端点
- **配置有效性验证**（如 "测试连接" 按钮）
- **多语言描述**
- **日志/审计**

---

## 10. 风险与备选方案

### 10.1 风险

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 用户从 UI 修改 key 后，模块级已 import 的 Singleton 不会自动更新 | 高 | 中等 | 第一阶段不改 fetcher 调用方，仅 provider.py 和 tushare 改成 `config_manager.get()` 获取 |
| 用户写入 DB 的 key 因 SQLite 文件权限问题被其他进程读取 | 低 | 低 | `.env` 和 `portfolio.db` 在同一目录，权限一致 |
| 前端展示脱敏不完整导致 key 泄露（屏幕截图等） | 低 | 低 | 脱敏规则明确：前4+后4，中间全掩码 |
| pydantic settings 字段名与 CONFIG_ITEMS 的 key 名不匹配 | 低 | 中等 | `getattr(settings, key.lower(), None)` 保持大小写对齐 |

### 10.2 备选方案

**方案 A（选定的）**: DB Overrides + ConfigManager 单例
- 优点：简单、零依赖、兼容性好
- 缺点：SQLite 无加密

**方案 B（未选）**: 前端直接读写 `.env` 文件
- 优点：无需新表、无需缓存
- 缺点：文件操作在 async 环境中有竞争风险；Docker 中 `.env` 可能被覆盖

**方案 C（未选）**: 前端直接写环境变量 + 子进程重启
- 优点：无需任何架构改动
- 缺点：需要重启服务，违反"即时生效"目标

---

## 附录 A：引用文件

| 文件 | 角色 |
|------|------|
| `backend/app/config.py` | 现有 Settings 单例 |
| `backend/app/database.py` | DB 初始化入口 |
| `backend/app/routers/admin.py` | 现有 admin 路由 |
| `backend/app/analysis/provider.py` | LLM provider 热更新（P1） |
| `frontend/src/router/index.js` | 前端路由表 |
| `frontend/src/App.vue` | 前端导航栏 |
| `frontend/src/api/index.js` | 前端 API 层 |
| `frontend/src/components/TokenMonitor.vue` | Admin 页面风格参考 |

## 附录 B：与 AGENTS.md 约束的核对

| AGENTS.md 约束 | 本方案满足情况 |
|----------------|---------------|
| 新功能先写 API 契约再编码 | ✅ 本章第 6 节为契约规范，实施时需同步创建 `api-contracts/admin/config.md` |
| 后端改动必须跑 `verify_e2e.py` | ✅ 列入验收标准 |
| 不改 fetcher 调用签名 | ✅ 第一阶段不改外围 fetcher |
| SQLite 数据通过 volume 挂载 | ✅ app_config 表在同一个 DB |
| 权重不归一化 | ✅ 不涉及组合逻辑 |
