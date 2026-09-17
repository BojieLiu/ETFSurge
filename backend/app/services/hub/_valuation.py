# -*- coding: utf-8 -*-
"""Valuation mixin — 指数/板块 PE 历史 + 250 天滚动存储（L2 P0）.

- 内存缓存 6h（估值日级变化）；空结果不缓存（靠 fetcher 1h 失败缓存防刷）。
- 落盘幂等：(kind, key, as_of) 唯一，重复写入忽略；每 key 只留最近 250 个 as_of。
- raw sqlite 同步读写（照抄 hub/_common.py 快照模式，busy_timeout 配套）。
- 导入 ValuationHistory 模型：hub 启动期被导入即注册进 Base.metadata，
  init_db 的 create_all 生效（P1 门面接线后激活）。
"""

from __future__ import annotations

import logging
import sqlite3
import time

from ...config import settings
from ...fetchers.valuation_fetcher import (
    fetch_index_valuation_history,
    fetch_sector_pe_snapshot,
)
from ...models.valuation_history import ValuationHistory  # noqa: F401（注册建表用）

logger = logging.getLogger(__name__)

_INDEX_TTL = 6 * 3600
_SECTOR_TTL = 6 * 3600
_KEEP_PER_KEY = 250

_VAL_COLS = {"pe_1", "pe_2", "div_1", "div_2",
             "pe_wavg", "pe_median", "pe_avg"}

_DDL = """
CREATE TABLE IF NOT EXISTS valuation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind VARCHAR(16) NOT NULL,
    key VARCHAR(40) NOT NULL,
    pe_1 FLOAT, pe_2 FLOAT, div_1 FLOAT, div_2 FLOAT,
    pe_wavg FLOAT, pe_median FLOAT, pe_avg FLOAT,
    as_of VARCHAR(24) NOT NULL,
    created_at TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_val_kind_key_asof
    ON valuation_history (kind, key, as_of);
CREATE INDEX IF NOT EXISTS ix_val_kind_key
    ON valuation_history (kind, key);
"""


def _valuation_db_path() -> str:
    """估值库路径（与主库同源，测试可 monkeypatch）。"""
    return settings.database_url.replace("sqlite+aiosqlite:///", "")


def _ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(_DDL)


class ValuationMixin:
    """混入门面即获得 get_index_valuation / get_sector_valuation 等能力."""

    # ── 读（内存 6h 缓存） ──────────────────────────────────────────

    def get_index_valuation(self, symbol: str) -> list[dict]:
        now = time.time()
        cache = self.__dict__.setdefault("_index_valuation_cache", {})
        ts = self.__dict__.setdefault("_index_valuation_cache_ts", {})
        if symbol in cache and (now - ts.get(symbol, 0)) < _INDEX_TTL:
            return cache[symbol]
        rows = fetch_index_valuation_history(symbol)
        if rows:
            cache[symbol] = rows
            ts[symbol] = now
            self.persist_index_valuation(symbol, rows)
        return rows

    def get_sector_valuation(self, date: str | None = None) -> list[dict]:
        now = time.time()
        cache = self.__dict__.setdefault("_sector_valuation_cache", {})
        ts = self.__dict__.setdefault("_sector_valuation_cache_ts", {})
        key = date or "latest"
        if key in cache and (now - ts.get(key, 0)) < _SECTOR_TTL:
            return cache[key]
        rows = fetch_sector_pe_snapshot(date=date)
        if rows:
            cache[key] = rows
            ts[key] = now
            self.persist_sector_valuation(rows)
        return rows

    # ── 写（幂等 + 250 裁剪） ───────────────────────────────────────

    def persist_index_valuation(self, symbol: str, rows: list[dict]) -> int:
        recs = [{
            "kind": "index", "key": symbol,
            "pe_1": r.get("pe_1"), "pe_2": r.get("pe_2"),
            "div_1": r.get("div_1"), "div_2": r.get("div_2"),
            "pe_wavg": None, "pe_median": None, "pe_avg": None,
            "as_of": r.get("date", ""),
        } for r in (rows or []) if r.get("date")]
        return self._persist_many(recs)

    def persist_sector_valuation(self, rows: list[dict]) -> int:
        recs = [{
            "kind": "sector", "key": r.get("ind_code", ""),
            "pe_1": None, "pe_2": None, "div_1": None, "div_2": None,
            "pe_wavg": r.get("pe_wavg"), "pe_median": r.get("pe_median"),
            "pe_avg": r.get("pe_avg"),
            "as_of": r.get("as_of", ""),
        } for r in (rows or []) if r.get("ind_code") and r.get("as_of")]
        return self._persist_many(recs)

    def _persist_many(self, recs: list[dict]) -> int:
        if not recs:
            return 0
        try:
            with sqlite3.connect(_valuation_db_path(), timeout=10) as conn:
                conn.execute("PRAGMA busy_timeout=30000")
                _ensure_table(conn)
                conn.executemany(
                    "INSERT OR IGNORE INTO valuation_history "
                    "(kind, key, pe_1, pe_2, div_1, div_2, "
                    " pe_wavg, pe_median, pe_avg, as_of, created_at) "
                    "VALUES (:kind, :key, :pe_1, :pe_2, :div_1, :div_2, "
                    " :pe_wavg, :pe_median, :pe_avg, :as_of, "
                    " CURRENT_TIMESTAMP)",
                    recs,
                )
                # 每 (kind, key) 只留最近 250 个 as_of
                for kind, key in {(r["kind"], r["key"]) for r in recs}:
                    conn.execute(
                        "DELETE FROM valuation_history WHERE kind=? AND key=? "
                        "AND id NOT IN (SELECT id FROM valuation_history "
                        "WHERE kind=? AND key=? "
                        "ORDER BY as_of DESC, id DESC LIMIT ?)",
                        (kind, key, kind, key, _KEEP_PER_KEY),
                    )
                return conn.total_changes
        except Exception as e:
            logger.warning("[valuation] persist failed: %s", e)
            return 0

    # ── 读历史（分位输入） ─────────────────────────────────────────

    def get_valuation_history(self, kind: str, key: str, col: str) -> list[float]:
        """某 key 单列历史（as_of 降序，None 已滤除）。col 必须白名单防注入。"""
        if col not in _VAL_COLS:
            raise ValueError(f"unknown valuation column: {col}")
        try:
            with sqlite3.connect(_valuation_db_path(), timeout=10) as conn:
                conn.execute("PRAGMA busy_timeout=30000")
                _ensure_table(conn)
                cur = conn.execute(
                    f"SELECT {col} FROM valuation_history "  # noqa: S608（col 已白名单）
                    "WHERE kind=? AND key=? AND "
                    f"{col} IS NOT NULL ORDER BY as_of DESC",
                    (kind, key),
                )
                return [float(r[0]) for r in cur.fetchall()]
        except Exception as e:
            logger.warning("[valuation] read history failed: %s", e)
            return []

    def count_valuation_rows(self, kind: str, key: str) -> int:
        try:
            with sqlite3.connect(_valuation_db_path(), timeout=10) as conn:
                conn.execute("PRAGMA busy_timeout=30000")
                _ensure_table(conn)
                row = conn.execute(
                    "SELECT COUNT(*) FROM valuation_history WHERE kind=? AND key=?",
                    (kind, key),
                ).fetchone()
                return int(row[0]) if row else 0
        except Exception:
            return 0
