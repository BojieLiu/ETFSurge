import socket
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings
from pydantic import Field

# 解析 .env 为绝对路径, 避免依赖进程工作目录
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_DIR = _BACKEND_DIR.parent  # E:\ETF_Surge
_DATA_DIR = _PROJECT_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_ENV_FILE = _BACKEND_DIR / ".env"


# ── P0.5: IPv4 优先策略 ─────────────────────────────────────────
# 强制所有 socket 连接使用 IPv4，规避东方财富 CDN 的 IPv6 路由问题
_original_getaddrinfo = socket.getaddrinfo


def enable_ipv4_only() -> None:
    """Monkey-patch socket.getaddrinfo to force IPv4 (AF_INET) only."""
    def _ipv4_getaddrinfo(host, port, family=0, socktype=0, proto=0, flags=0):
        return _original_getaddrinfo(host, port, socket.AF_INET, socktype, proto, flags)
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

    # connnection pool 配置
    pool_connections: int = 30
    pool_maxsize: int = 60

    # 降级策略（Z28: 与 task_manager/design_report 240s 三层对齐，免费模型高峰排队 >90s）
    llm_primary_provider: str = "opencode_zen"
    llm_fallback_provider: str = "deepseek"
    llm_primary_timeout: int = 240
    llm_fallback_timeout: int = 240

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


settings = Settings()
