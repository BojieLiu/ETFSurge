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
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"
    # 日志：级别（DEBUG/INFO/WARNING/ERROR）与可选日志文件路径
    log_level: str = "INFO"
    log_file: str = ""

    # 端口配置（可选，便于统一管理）
    backend_port: int = 8000
    frontend_dev_port: int = 5173

    class Config:
        env_file = str(_ENV_FILE)
        env_file_encoding = "utf-8"
        populate_by_name = True  # 允许用别名（alias）读取


settings = Settings()
