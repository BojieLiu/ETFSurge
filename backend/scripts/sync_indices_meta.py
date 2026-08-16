"""round25 R30: `scripts/` 兼容 shim——生产代码已移入 `app/fetchers/sync_indices_meta.py`
（scripts/ 被 .dockerignore 排除出容器镜像，容器内无法 import 此包）。

保留本 shim 仅用于本地手动 CLI：`python -m scripts.sync_indices_meta`。容器/生产路径
一律走 `app.fetchers.sync_indices_meta`（services 层已改指向）。
"""
from app.fetchers.sync_indices_meta import *  # noqa: F401,F403
from app.fetchers.sync_indices_meta import (  # noqa: F401
    collect_all,
    sync,
    _to_pinyin,
    _STATIC_EXTRA_INDICES,
    _fetch_sina_a_indices,
    _fetch_sina_hk_indices,
    _fetch_ths_industry_indices,
    _fetch_ths_concept_indices,
)