"""核心指数按实例市场切换: A 股四大指数 / 美股基准 ETF。"""
from __future__ import annotations

import polars as pl
import pytest

from app.api import overview
from app.services import index_const, index_sync, market_overview_builder


def test_core_index_lists_per_market():
    assert index_const.core_index_symbols("cn") == ("000001.SH", "399001.SZ", "399006.SZ", "000680.SH")
    assert index_const.core_index_symbols("us") == ("SPY", "QQQ", "DIA", "IWM")
    # 兼容常量保持 A 股清单不变
    assert index_const.core_index_symbols("cn") == index_const.CORE_INDEX_SYMBOLS


@pytest.mark.parametrize("market", ["cn", "us"])
def test_overview_index_cards_follow_active_market(monkeypatch, market):
    monkeypatch.setattr(index_const, "active_market", lambda: market)
    expected = index_const.core_index_names(market)
    builder_rows = market_overview_builder._index_quotes(None, None)
    assert [r["symbol"] for r in builder_rows] == list(expected)
    assert [r["name"] for r in builder_rows] == list(expected.values())


class _OverviewState:
    quote_service = None
    repo = None


class _OverviewApp:
    state = _OverviewState()


class _OverviewRequest:
    app = _OverviewApp()


def test_overview_api_index_cards_use_us_list(monkeypatch):
    monkeypatch.setattr(index_const, "active_market", lambda: "us")
    rows = overview._index_quotes(_OverviewRequest())
    assert [r["symbol"] for r in rows] == ["SPY", "QQQ", "DIA", "IWM"]


class _FakeRepo:
    def __init__(self):
        self.saved: pl.DataFrame | None = None

    def save_index_instruments(self, df):
        self.saved = df

    def save_etf_instruments(self, df):
        raise AssertionError("pull_etf=False 不应写 ETF 维表")

    def refresh_index_views(self):
        pass


class _IndexProvider:
    def __init__(self, items):
        self.items = items

    def get_instruments(self, asset_type):
        assert asset_type == "index"
        return self.items


def _route_daily_to(monkeypatch, provider):
    from app.data_providers import custom as custom_sources

    monkeypatch.setattr(index_sync.preferences, "get_daily_data_provider", lambda: "yahoo_us")
    monkeypatch.setattr(custom_sources, "is_custom_provider", lambda n: n == "yahoo_us")
    monkeypatch.setattr(custom_sources, "get_provider", lambda n: provider)


def test_index_instruments_come_from_custom_daily_provider(monkeypatch):
    _route_daily_to(monkeypatch, _IndexProvider([{"symbol": "SPY", "name": "标普500 (SPY)"},
                                                 {"symbol": "QQQ", "name": "纳指100 (QQQ)"}]))

    def no_tickflow(*args, **kwargs):
        raise AssertionError("自定义源接管指数维表时不应请求 TickFlow")

    monkeypatch.setattr(index_sync, "_fetch_instruments_by_type", no_tickflow)
    repo = _FakeRepo()
    assert index_sync.sync_index_instruments(repo, pull_index=True, pull_etf=False) == 2
    assert repo.saved["symbol"].to_list() == ["QQQ", "SPY"]
    assert set(repo.saved["asset_type"].to_list()) == {"index"}
    assert repo.saved["code"].to_list() == ["QQQ", "SPY"]


def test_index_instruments_fall_back_to_tickflow_when_provider_has_none(monkeypatch):
    _route_daily_to(monkeypatch, _IndexProvider([]))
    calls = []

    def fake_tickflow(instrument_type, label):
        calls.append(instrument_type)
        return pl.DataFrame({"symbol": ["000001.SH"], "name": ["上证指数"], "code": ["000001"], "asset_type": ["index"]})

    monkeypatch.setattr(index_sync, "_fetch_instruments_by_type", fake_tickflow)
    repo = _FakeRepo()
    assert index_sync.sync_index_instruments(repo, pull_index=True, pull_etf=False) == 1
    assert calls == ["index"]


def test_settings_payload_exposes_market_and_core_indexes(monkeypatch):
    import app.market as market_module
    from app.api import settings as settings_api

    monkeypatch.setattr(market_module, "active_market", lambda: "us")
    payload = settings_api._market_payload()
    assert payload["market"] == "us"
    assert [i["symbol"] for i in payload["core_indexes"]] == ["SPY", "QQQ", "DIA", "IWM"]
