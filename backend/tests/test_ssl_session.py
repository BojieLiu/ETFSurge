"""Tests: SSL session reuse in news_fetcher (7.1 P2).

TDD: Written before implementation.
Covers:
  - news_fetcher uses requests.Session() instead of raw requests.get()
  - Session is a module-level singleton
  - Session has appropriate default headers
"""
import pytest


def test_news_fetcher_has_http_session():
    """news_fetcher should define _http_session as a requests.Session()."""
    from app.fetchers.news_fetcher import _http_session
    import requests

    assert isinstance(_http_session, requests.Session)
    # Should have User-Agent header
    assert "User-Agent" in _http_session.headers
    assert "Chrome" in _http_session.headers["User-Agent"]


def test_session_has_accept_headers():
    """Session should have appropriate accept headers."""
    from app.fetchers.news_fetcher import _http_session

    assert "Accept" in _http_session.headers
    assert "Accept-Language" in _http_session.headers


def test_session_is_module_level():
    """_http_session should be accessible as a module attribute."""
    import app.fetchers.news_fetcher as nf
    assert hasattr(nf, "_http_session")
    assert nf._http_session is not None
