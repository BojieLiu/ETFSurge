"""round29 续轮: `scripts/` 兼容 shim——生产代码已移入 `app/fetchers/sync_indices.py`
（scripts/ 被 .dockerignore 排除出容器镜像，容器内无法 import 此包）。

保留本 shim 仅用于本地手动 CLI：`python -m scripts.sync_indices`。容器/生产路径
一律走 `app.fetchers.sync_indices`。
"""
from app.fetchers.sync_indices import *  # noqa: F401,F403
from app.fetchers.sync_indices import (  # noqa: F401
    sync,
)

if __name__ == "__main__":
    import asyncio

    asyncio.run(sync())
