from __future__ import annotations

import polars as pl
import pytest

from app.market import US_SYMBOL_PATTERN, is_us_symbol, market_of


@pytest.mark.parametrize(
    ("symbol", "expected"),
    [
        ("600519.SH", "cn"),
        ("000001.SZ", "cn"),
        ("300750.SZ", "cn"),
        ("830799.BJ", "cn"),
        ("AAPL", "us"),
        ("A", "us"),
        ("GOOGL", "us"),
        ("BRK-B", "us"),
        ("BF-B", "us"),
        # 不合规格式一律 None, 不猜测
        ("aapl", None),
        ("AAPL.US", None),
        ("BRK.B", None),
        ("TOOLONG", None),
        ("600519", None),
        ("600519.HK", None),
        (" AAPL", None),
        ("", None),
        (None, None),
    ],
)
def test_market_of(symbol, expected):
    assert market_of(symbol) == expected


def test_is_us_symbol():
    assert is_us_symbol("MSFT")
    assert not is_us_symbol("600519.SH")
    assert not is_us_symbol(None)


def test_polars_pattern_matches_python_rule():
    """polars 向量路径复用同一正则, 两边判定必须一致。"""
    symbols = ["AAPL", "BRK-B", "600519.SH", "aapl", "BRK.B", "TOOLONG"]
    vectorized = pl.Series(symbols).str.contains(US_SYMBOL_PATTERN).to_list()
    assert vectorized == [is_us_symbol(s) for s in symbols]


class _Provider:
    def __init__(self, market=None):
        if market is not None:
            self.market = market


def _patch_daily_provider(monkeypatch, name, provider=None, *, registered=True):
    from app.data_providers import custom as custom_sources
    from app.services import preferences

    monkeypatch.setattr(preferences, "get_daily_data_provider", lambda: name)
    monkeypatch.setattr(custom_sources, "is_custom_provider", lambda n: registered and n == name)
    monkeypatch.setattr(custom_sources, "get_provider", lambda n: provider)


def test_active_market_follows_daily_provider(monkeypatch):
    from app.market import active_market

    _patch_daily_provider(monkeypatch, "tickflow")
    assert active_market() == "cn"
    _patch_daily_provider(monkeypatch, "yahoo_us", _Provider("us"))
    assert active_market() == "us"
    # 未声明 market 的插件 (fuyao/tdxquant) 与未注册的源保持 A 股
    _patch_daily_provider(monkeypatch, "fuyao", _Provider())
    assert active_market() == "cn"
    _patch_daily_provider(monkeypatch, "gone", _Provider("us"), registered=False)
    assert active_market() == "cn"


def test_active_market_falls_back_to_cn_on_error(monkeypatch):
    from app.market import active_market
    from app.services import preferences

    def boom():
        raise RuntimeError("prefs unreadable")

    monkeypatch.setattr(preferences, "get_daily_data_provider", boom)
    assert active_market() == "cn"
