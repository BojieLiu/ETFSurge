from pathlib import Path

from pydantic_settings import BaseSettings

# 解析 .env 为绝对路径, 避免依赖进程工作目录 (uvicorn 从不同目录启动时找不到)
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_PROJECT_DIR = _BACKEND_DIR.parent  # E:\ETF_Surge
_DATA_DIR = _PROJECT_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)
_ENV_FILE = _BACKEND_DIR / ".env"


class Settings(BaseSettings):
    # 绝对路径, 不依赖进程 CWD (之前相对 ./data 会因启动目录不同指向不同文件, 导致数据"丢失")
    database_url: str = f"sqlite+aiosqlite:///{_DATA_DIR / 'portfolio.db'}"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: str = "http://localhost:5173"
    deepseek_api_key: str = ""
    tushare_token: str = ""
    llm_provider: str = "deepseek"
    llm_model: str = "deepseek-v4-flash"

    class Config:
        env_file = str(_ENV_FILE)


settings = Settings()
