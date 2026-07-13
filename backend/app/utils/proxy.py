import os
import requests
from contextlib import contextmanager


# Patch requests.Session to bypass Windows system proxy
_orig_session_init = requests.Session.__init__


def _patched_session_init(self, *args, **kwargs):
    _orig_session_init(self, *args, **kwargs)
    self.trust_env = False


requests.Session.__init__ = _patched_session_init


@contextmanager
def no_proxy():
    saved = {}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "no_proxy", "NO_PROXY"):
        saved[key] = os.environ.pop(key, None)
    os.environ["no_proxy"] = "*"
    try:
        yield
    finally:
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)
