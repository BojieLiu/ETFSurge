import logging
import os
import re
import socket
from pathlib import Path
from typing import List

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)

# 解析 .env 为绝对路径, 避免依赖进程工作目录
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_DIR = _BACKEND_DIR.parent  # E:\ETF_Surge
_DATA_DIR = _PROJECT_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_ENV_FILE = _BACKEND_DIR / ".env"


# ── P0.5: IPv4 优先策略 + DNS 缓存（R44） ──────────────────────────
# 强制所有 socket 连接使用 IPv4，规避东方财富 CDN 的 IPv6 路由问题。
# 同时记忆化 DNS 解析结果：warmup 期间 _fetch_us_list 等会对同一 host
# 反复调用 socket.getaddrinfo（round27 实测 ~226 次 / 13.7s），缓存命中后
# 直接返回，省去实时 DNS。缓存为纯函数记忆化：无 I/O、无事件循环副作用，
# 对同步 getaddrinfo 调用安全（R44 验收要求第二次同 host 解析不再走真实 DNS）。
_original_getaddrinfo = socket.getaddrinfo

# (host, port) -> 解析结果。warmup 会话期内永久缓存即可（host 固定）；
# 如需更保守可改为 TTL，但 warmup 解析的 host 不会改变，永久更省时。
_dns_cache: dict[tuple, object] = {}


def _ipv4_getaddrinfo(host, port, family=0, socktype=0, proto=0, flags=0):
    """强制 IPv4 (AF_INET) 的 getaddrinfo，并记忆化解析结果（R44 DNS 缓存）。

    缓存键仅用 (host, port)：解析结果恒按 AF_INET 返回，family 入参不影响
    输出，故无需纳入键。命中缓存时不再调用底层 _original_getaddrinfo（真实
    DNS），从而消除 warmup 期间对同一 host 的重复 DNS 开销。
    """
    key = (host, port)
    cached = _dns_cache.get(key)
    if cached is not None:
        return cached
    result = _original_getaddrinfo(host, port, socket.AF_INET, socktype, proto, flags)
    _dns_cache[key] = result
    return result


def enable_ipv4_only() -> None:
    """Monkey-patch socket.getaddrinfo to force IPv4 (AF_INET) only."""
    socket.getaddrinfo = _ipv4_getaddrinfo


def disable_ipv4_only() -> None:
    """Restore original socket.getaddrinfo (allow both IPv4 and IPv6)."""
    socket.getaddrinfo = _original_getaddrinfo


# P0.5b: 模块加载时自动启用 IPv4 优先
enable_ipv4_only()


def _parse_cors_origins(v: str) -> List[str]:
    """解析逗号分隔的 CORS origins，支持 * 通配符"""
    if not v or v.strip() == "*":
        return ["*"]
    return [o.strip() for o in v.split(",") if o.strip()]


class Settings(BaseSettings):
    # 绝对路径, 不依赖进程 CWD (之前相对 ./data 会因启动目录不同指向不同文件, 导致数据"丢失")
    database_url: str = f"sqlite+aiosqlite:///{_DATA_DIR / 'portfolio.db'}"
    redis_url: str = "redis://localhost:6379/0"

    # R86 (round30): 数据目录（磁盘缓存落盘点，如 kline_cache.json / indices_cache.json）。
    # 由 `DATA_DIR` env 显式指定（容器挂载卷 /app/data）；未设置时在 validator 中从
    # database_url 解析（容器 `DATABASE_URL=sqlite+aiosqlite:////app/data/portfolio.db` →
    # `/app/data`），保证「缓存写到挂载卷」而非 os.path.dirname(__file__)×3 的源码目录。
    data_dir: str = ""

    # CORS：env 里用逗号分隔字符串，避免 pydantic_settings 误当 JSON 解析报错
    # 支持 CORS_ORIGINS (旧名) 和 CORS_ORIGINS_STR (新名)
    cors_origins_str: str = Field(
        default="http://localhost:5173,http://127.0.0.1:5173",
        alias="CORS_ORIGINS"
    )

    @property
    def cors_origins(self) -> List[str]:
        return _parse_cors_origins(self.cors_origins_str)

    deepseek_api_key: str = ""
    tushare_token: str = ""
    fred_api_key: str = ""

    # ── Market Data API Keys (free tiers, no proxy needed) ──
    alphavantage_api_key: str = ""
    finnhub_api_key: str = ""
    twelvedata_api_key: str = ""

    # ── LLM Provider 配置 ──────────────────────────────────────
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"

    # OpenCode Zen (主 provider)
    opencode_zen_api_key: str = ""
    opencode_zen_model: str = "deepseek-v4-flash-free"
    opencode_zen_api_url: str = "https://opencode.ai/zen/v1/chat/completions"

    # ── round35 §19: 三层 LLM 免费模型动态链（Zen 随机 → OpenRouter 按参 → DeepSeek 付费）──
    # OpenRouter 中间层（Zen 整层熔断后才承流的溢出层；key 入 .env 不入库）
    openrouter_api_key: str = ""
    openrouter_api_url: str = "https://openrouter.ai/api/v1/chat/completions"
    # 免费目录刷新 TTL 秒（lifespan 周期刷新 + last-known-good 兜底）
    llm_catalog_refresh_ttl: int = 600
    # Zen 层 JSON 路径限定子集（护栏 4）：逗号分隔模型白名单；空=全池随机。
    # 策略检查等结构化输出路径对指令跟随敏感，劣化时用此收紧随机域。
    llm_zen_allowed_models: str = ""

    # connnection pool 配置
    pool_connections: int = 30
    pool_maxsize: int = 60

    # 降级策略（round23 F9b: 收紧单请求超时，使 timeout×(retries+1)+退避 ≤ 外层预算；
    # 旧值 240s 远超策略检查 15/30/75s 分级预算，zen 持久 429 时每次白等 240s）。
    llm_primary_provider: str = "opencode_zen"
    llm_fallback_provider: str = "deepseek"
    llm_primary_timeout: int = 20
    llm_fallback_timeout: int = 45

    # 日志：级别（DEBUG/INFO/WARNING/ERROR）与可选日志文件路径
    log_level: str = "INFO"
    log_file: str = ""

    # 端口配置（可选，便于统一管理）
    backend_port: int = 8000
    frontend_dev_port: int = 5173

    # TickFlow (2026-08-09 接入)：免费历史日K/标的池来源，key 从 .env 读
    tickflow_api_key: str = ""

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        populate_by_name = True  # 允许用别名（alias）读取
        # 忽略未声明的环境变量（如 PROFILE_WARMUP / LOG_LEVEL 等进程级变量），
        # 避免容器环境中出现无关变量时 Settings 实例化崩溃（extra_forbidden）
        extra = "ignore"

    @model_validator(mode="after")
    def _resolve_data_dir(self) -> "Settings":
        """R86/R93: 解析 data_dir（DATA_DIR env → database_url 路径 → 项目默认）。

        容器内 database_url 为 `sqlite+aiosqlite:////app/data/portfolio.db`，
        本地为 `sqlite+aiosqlite:///E:/ETF_Surge/data/portfolio.db`——解析出
        路径目录即为缓存落盘点（与 DB 同目录，天然是挂载卷内）。

        R93 (round31): 旧正则 `:///+(.*)` 对容器 4 斜杠 URL 贪婪吃掉第 4 个前导
        斜杠 → 捕获 `app/data/portfolio.db`（丢 `/`）→ 相对路径 `app/data` →
        容器 CWD=/app 下解析为 /app/app/data（镜像层，重启即丢）。本地恰绿是
        Windows 盘符使相对值仍为绝对。改为 `:///?(.*)` 保留第 4 斜杠，并后置
        断言 data_dir 为绝对路径——非绝对（解析仍丢前导斜杠的怪 URL）WARNING +
        回退项目默认 `_DATA_DIR`。
        """
        if self.data_dir:
            # 已由 DATA_DIR env 显式指定
            return self
        _m = re.match(r"^sqlite(?:\+\w+)?:///?(.*)", self.database_url)
        if _m:
            _db_path = _m.group(1).split("?")[0]
            if _db_path:
                _candidate = str(Path(_db_path).parent)
                if os.path.isabs(_candidate):
                    self.data_dir = _candidate
                    return self
                logger.warning(
                    "[config] database_url 解析出非绝对 data_dir=%r（URL=%r）"
                    " — 回退项目默认 %s（容器内写到非挂载卷会在重启后丢失，R93）",
                    _candidate, self.database_url, _DATA_DIR,
                )
        self.data_dir = str(_DATA_DIR)
        return self


settings = Settings()
