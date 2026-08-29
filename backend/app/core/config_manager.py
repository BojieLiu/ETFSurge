"""
ConfigManager — 运行时配置管理器。

优先级: DB overrides > .env (pydantic settings)

使用方式:
    from ..core.config_manager import config_manager
    api_key = config_manager.get("DEEPSEEK_API_KEY")  # DB > .env
    config_manager.set_override("DEEPSEEK_API_KEY", "sk-xxx")
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, text

from ..config import settings
from ..core.logging import get_logger

logger = get_logger(__name__)


# ── 所有可配置项的元数据 ─────────────────────────
CONFIG_ITEMS: list[dict] = [
    {"key": "DEEPSEEK_API_KEY",       "label": "DeepSeek API Key",      "group": "LLM 服务",
     "description": "DeepSeek 官方 API 密钥，用于 LLM 分析和报告生成（降级线路）",
     "placeholder": "sk-..."},
    {"key": "OPENCODE_ZEN_API_KEY",   "label": "OpenCode Zen API Key",  "group": "LLM 服务",
     "description": "OpenCode Zen 平台 API 密钥，用于 LLM 分析和报告生成（主力线路）",
     "placeholder": "sk-..."},
    {"key": "TUSHARE_TOKEN",          "label": "Tushare Token",         "group": "数据源",
     "description": "Tushare Pro 接口 Token，用于 A 股行情数据",
     "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
    {"key": "ALPHAVANTAGE_API_KEY",   "label": "Alpha Vantage API Key", "group": "数据源",
     "description": "Alpha Vantage API 密钥，用于美股实时行情（备用）",
     "placeholder": "xxxxxxxxxx"},
    {"key": "FINNHUB_API_KEY",        "label": "Finnhub API Key",       "group": "数据源",
     "description": "Finnhub API 密钥，用于美股数据",
     "placeholder": "xxxxxxxxxx"},
    {"key": "TWELVEDATA_API_KEY",     "label": "Twelve Data API Key",   "group": "数据源",
     "description": "Twelve Data API 密钥，用于行情数据",
     "placeholder": "xxxxxxxxxx"},
    {"key": "FRED_API_KEY",           "label": "FRED API Key",          "group": "数据源",
     "description": "FRED 经济指标 API 密钥，用于宏观数据",
     "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"},
]


class ConfigManager:
    """运行时配置管理器。

    优先级: DB overrides > .env (pydantic settings)
    线程安全: 所有读写操作都直接走 DB，不维护本地缓存，
              避免多线程/多协程的缓存一致性问题。
    """

    def __init__(self):
        self._db_session_factory: Any = None

    def init(self, session_factory) -> None:
        """注入 DB session factory。"""
        self._db_session_factory = session_factory

    async def get(self, key: str) -> Optional[str]:
        """获取配置值，优先级: DB overrides > .env。

        不缓存，每次读取都查 DB（配置操作低频，DB 查询开销可忽略）。
        """
        if self._db_session_factory is None:
            # Fallback to .env if DB not initialized
            return self._get_env(key)

        try:
            async with self._db_session_factory() as session:
                from ..models.app_config import AppConfig
                result = await session.execute(
                    select(AppConfig).where(AppConfig.key == key)
                )
                row = result.scalar_one_or_none()
                if row is not None:
                    return row.value
        except Exception as e:
            logger.warning("[config] DB read failed for %s: %s", key, e)

        return self._get_env(key)

    async def set_override(self, key: str, value: str) -> None:
        """写入 DB override，UPSERT 语义。"""
        if self._db_session_factory is None:
            logger.warning("[config] DB not initialized, cannot set %s", key)
            return

        try:
            async with self._db_session_factory() as session:
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert

                from ..models.app_config import AppConfig

                upsert = sqlite_insert(AppConfig).values(
                    key=key, value=value, updated_at=datetime.utcnow()
                )
                upsert = upsert.on_conflict_do_update(
                    index_elements=["key"],
                    set_=dict(value=value, updated_at=datetime.utcnow()),
                )
                await session.execute(upsert)
                await session.commit()
                logger.info("[config] %s updated", key)
        except Exception as e:
            logger.exception("[config] Failed to set %s: %s", key, e)

    async def delete_override(self, key: str) -> None:
        """删除 DB override，恢复为 .env 值。"""
        if self._db_session_factory is None:
            return

        try:
            async with self._db_session_factory() as session:
                await session.execute(
                    text("DELETE FROM app_config WHERE key = :key"),
                    {"key": key},
                )
                await session.commit()
                logger.info("[config] %s override deleted", key)
        except Exception as e:
            logger.exception("[config] Failed to delete %s: %s", key, e)

    async def get_all(self) -> dict[str, Any]:
        """返回所有配置项的当前值（含 DB overrides + .env fallback）。"""
        items = []
        for item_def in CONFIG_ITEMS:
            key = item_def["key"]
            db_val = await self.get(key)
            env_val = self._get_env(key)
            from_env = db_val == env_val
            items.append({
                "key": key,
                "label": item_def["label"],
                "group": item_def["group"],
                "description": item_def["description"],
                "value": db_val if db_val else "",
                "configured": db_val is not None,
                "from_env": from_env,
            })
        return {"items": items, "total": len(items)}

    async def list_keys_with_prefix(self, prefix: str) -> list[str]:
        """列出 DB 中所有以 prefix 开头的 key. 用于 round46 mark_excluded 启动加载.

        不走 CONFIG_ITEMS (固定清单), 直接 raw SELECT. 返 list[str] (空 DB / 未
        初始化返 []). 失败 WARN 后返 [] (降级为内存默认空).
        """
        if self._db_session_factory is None:
            return []
        try:
            async with self._db_session_factory() as session:
                from sqlalchemy import select
                from ..models.app_config import AppConfig
                result = await session.execute(
                    select(AppConfig.key).where(AppConfig.key.like(f"{prefix}%"))
                )
                return [row[0] for row in result.all()]
        except Exception as e:
            logger.warning("[config] list_keys_with_prefix(%s) failed: %s", prefix, e)
            return []

    async def set_kv(self, key: str, value: str) -> bool:
        """通用 KV 写入 (与 set_override 等价, 命名通用化). 返 True 成功 / False 失败."""
        if self._db_session_factory is None:
            return False
        try:
            async with self._db_session_factory() as session:
                from sqlalchemy.dialects.sqlite import insert as sqlite_insert
                from ..models.app_config import AppConfig
                upsert = sqlite_insert(AppConfig).values(
                    key=key, value=value, updated_at=datetime.utcnow()
                )
                upsert = upsert.on_conflict_do_update(
                    index_elements=["key"],
                    set_=dict(value=value, updated_at=datetime.utcnow()),
                )
                await session.execute(upsert)
                await session.commit()
                return True
        except Exception as e:
            logger.exception("[config] set_kv(%s) failed: %s", key, e)
            return False

    async def delete_kv(self, key: str) -> bool:
        """通用 KV 删除. 返 True 删了行 / False 未删 (行不存在或失败)."""
        if self._db_session_factory is None:
            return False
        try:
            async with self._db_session_factory() as session:
                from sqlalchemy import delete
                from ..models.app_config import AppConfig
                result = await session.execute(
                    delete(AppConfig).where(AppConfig.key == key)
                )
                await session.commit()
                return result.rowcount > 0
        except Exception as e:
            logger.exception("[config] delete_kv(%s) failed: %s", key, e)
            return False

    @staticmethod
    def _get_env(key: str) -> Optional[str]:
        """从 pydantic settings 读取 .env 值。"""
        env_key = key.lower()
        env_map = {
            "deepseek_api_key": settings.deepseek_api_key,
            "opencode_zen_api_key": settings.opencode_zen_api_key,
            "tushare_token": settings.tushare_token,
            "alphavantage_api_key": settings.alphavantage_api_key,
            "finnhub_api_key": settings.finnhub_api_key,
            "twelvedata_api_key": settings.twelvedata_api_key,
            "fred_api_key": settings.fred_api_key,
        }
        val = env_map.get(env_key)
        if val and not val.startswith("your_"):
            return val
        return None


# 全局单例
config_manager = ConfigManager()
