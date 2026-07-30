"""F11: opt-in fast JSON shim for akshare's demjson usage.

The system diagnosis attributed ~8.6s of warmup CPU to `akshare`'s use of the
pure-Python `demjson` decoder. `demjson` handles non-strict JSON (trailing
commas, comments, unquoted keys) that the stdlib `json` / `orjson` reject.

We cannot safely replace `demjson` wholesale (akshare relies on its leniency),
so this module installs a *guarded* shim: `demjson.decode` first tries a fast
strict decoder (`orjson` → `json`) and only falls back to the real `demjson`
when the strict path raises. This captures the common strict-JSON responses
(significant speed-up) while preserving correctness for genuinely lenient input.

Activation is opt-in via env `ETF_FAST_JSON=1` so it never destabilizes the
default path. `install_demjson_shim()` is idempotent and unit-tested.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_installed = False


def _strict_decode(text: str):
    """Try orjson then stdlib json. Raise on non-strict input."""
    try:
        import orjson
        return orjson.loads(text)
    except ImportError:
        return json.loads(text)
    except Exception:
        # orjson missing or strict parse failed -> let caller fall back
        raise


def install_demjson_shim() -> bool:
    """Wrap demjson.decode with a fast strict-first path. Returns True if applied.

    Safe: any failure inside the shim defers to the original demjson decoder.
    """
    global _installed
    if _installed:
        return True

    try:
        import demjson
    except Exception as _e:
        logger.info("[fast_json] demjson not importable, shim skipped: %s", _e)
        return False

    original = getattr(demjson, "decode", None)
    if original is None or getattr(original, "_etf_shim", False):
        return False

    def _shim(text, *args, **kwargs):
        try:
            return _strict_decode(text)
        except Exception:
            # Non-strict input (or decode error in strict path) -> original
            return original(text, *args, **kwargs)

    _shim._etf_shim = True  # type: ignore
    demjson.decode = _shim
    _installed = True
    logger.info("[fast_json] demjson.decode shim installed (orjson/json fast path)")
    return True


def reset_demjson_shim():
    """Test helper: undo installation flag (does not restore original)."""
    global _installed
    _installed = False
