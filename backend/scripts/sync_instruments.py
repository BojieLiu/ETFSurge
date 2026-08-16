"""round25 R30: `scripts/` 兼容 shim——生产代码已移入 `app/fetchers/sync_instruments.py`
（scripts/ 被 .dockerignore 排除出容器镜像，容器内无法 import 此包）。

保留本 shim 仅用于本地手动 CLI：`python -m scripts.sync_instruments`。容器/生产路径
一律走 `app.fetchers.sync_instruments`（services 层已改指向）。
"""
from app.fetchers.sync_instruments import *  # noqa: F401,F403
from app.fetchers.sync_instruments import (  # noqa: F401
    collect_all,
    sync,
    _to_pinyin,
    _fetch_a_stock_list,
    _fetch_etf_list,
    _fetch_hk_list,
    _fetch_hk_etf_list,
    _fetch_us_list,
    _fetch_akshare_list,
)