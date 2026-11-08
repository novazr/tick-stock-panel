"""Yahoo 美股插件契约测试 (假客户端, 不依赖真实网络)。

覆盖: 拆股还原原始价、股→手、除权因子推导与 pipeline 前复权一致、
当日未定型 K 线、分批与整批失败语义、标的维表与能力声明。
"""
from __future__ import annotations

from datetime import date, datetime

import polars as pl
import pytest

from app.data_providers.base import ProviderRequestError
from app.indicators.pipeline import _apply_adj_factor
from app.plugins.yahoo_us import provider as yp
from app.plugins.yahoo_us.client import (
    NY_TZ,
    ChartData,
    YahooError,
    YahooNotFoundError,
    parse_chart,
)


def _bar(day: date, close: float, volume: float = 1_000_000.0) -> dict:
    return {"date": day, "open": close, "high": close, "low": close, "close": close, "volume": volume}


def _split_chart() -> ChartData:
    """拆股前两天 + 4:1 拆股当日 + 之后一天; 价格是 Yahoo 的拆股调整口径。"""
    return ChartData(
        symbol="AAPL",
        meta={},
        bars=[
            _bar(date(2020, 8, 27), 125.0, 400_000.0),
            _bar(date(2020, 8, 28), 124.8, 400_000.0),
            _bar(date(2020, 8, 31), 129.0, 900_000.0),
            _bar(date(2020, 9, 1), 134.0, 800_000.0),
        ],
        splits=[(date(2020, 8, 31), 4.0)],
        dividends=[],
    )


# ---------------------------------------------------------------- 解析


def test_parse_chart_drops_null_placeholders_and_reads_events():
    payload = {"chart": {"error": None, "result": [{
        "meta": {"symbol": "AAPL"},
        "timestamp": [1598621400, 1598880600, 1598967000],  # 08-28 / 08-31 / 09-01 09:30 ET
        "indicators": {"quote": [{
            "open": [126.0, 127.6, None], "high": [126.4, 131.0, None],
            "low": [124.6, 126.0, None], "close": [124.8, 129.0, None],
            "volume": [1.0e8, 2.2e8, None],
        }]},
        "events": {
            "splits": {"1598880600": {"date": 1598880600, "numerator": 4.0, "denominator": 1.0}},
            "dividends": {"1597325400": {"date": 1597325400, "amount": 0.205}},
        },
    }]}}
    chart = parse_chart("AAPL", payload)
    assert [b["date"] for b in chart.bars] == [date(2020, 8, 28), date(2020, 8, 31)]
    assert chart.splits == [(date(2020, 8, 31), 4.0)]
    assert chart.dividends == [(date(2020, 8, 13), 0.205)]


def test_parse_chart_not_found_is_distinct_error():
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    with pytest.raises(YahooNotFoundError):
        parse_chart("ZZZZ", payload)
    with pytest.raises(YahooError):
        parse_chart("AAPL", {"chart": {"result": []}})


# ---------------------------------------------------------------- 单位与原始价


def test_raw_daily_rows_restore_pre_split_prices_and_convert_volume_to_hands():
    rows = yp.raw_daily_rows(_split_chart())
    by_day = {r["date"]: r for r in rows}
    # 拆股前: 原始价 = Yahoo 价 × 4, 原始股数 = Yahoo 股数 ÷ 4, 再 ÷100 取整成手
    assert by_day[date(2020, 8, 28)]["close"] == pytest.approx(499.2)
    assert by_day[date(2020, 8, 28)]["volume"] == 1000.0
    # 拆股当日及之后: 已是拆股后口径, 原样
    assert by_day[date(2020, 8, 31)]["close"] == pytest.approx(129.0)
    assert by_day[date(2020, 8, 31)]["volume"] == 9000.0
    # 成交额不伪造
    assert all(r["amount"] is None for r in rows)


def test_volume_hands_are_floored():
    chart = ChartData("MSFT", {}, [_bar(date(2026, 7, 1), 500.0, 12_345.0)])
    assert yp.raw_daily_rows(chart)[0]["volume"] == 123.0


# ---------------------------------------------------------------- 除权因子


def test_split_event_factor_equals_split_ratio():
    events = yp.adjustment_events(_split_chart(), date(2020, 1, 1), date(2020, 12, 31))
    assert len(events) == 1
    ev = events[0]
    assert ev["trade_date"] == date(2020, 8, 31)
    assert ev["ex_factor"] == pytest.approx(4.0)
    assert ev["bonus"] == pytest.approx(3.0)
    assert ev["prev_close"] == pytest.approx(499.2)


def test_split_factor_makes_pipeline_reproduce_split_adjusted_series():
    chart = _split_chart()
    raw = pl.DataFrame(yp.raw_daily_rows(chart)).select("symbol", "date", "open", "high", "low", "close")
    factors = pl.DataFrame(yp.adjustment_events(chart, date(2020, 1, 1), date(2020, 12, 31))).select(
        "symbol", "trade_date", "ex_factor",
    )
    adjusted = _apply_adj_factor(raw, factors).sort("date")["close"].to_list()
    assert adjusted == pytest.approx([b["close"] for b in chart.bars])


def test_dividend_factor_uses_raw_dividend_restored_for_later_splits():
    chart = ChartData(
        symbol="AAPL",
        meta={},
        bars=[_bar(date(2020, 8, 6), 113.0), _bar(date(2020, 8, 7), 111.1)],
        splits=[(date(2020, 8, 31), 4.0)],
        # Yahoo 分红按之后的拆股调整: 0.205 = 原始 0.82 ÷ 4
        dividends=[(date(2020, 8, 7), 0.205)],
    )
    events = yp.adjustment_events(chart, date(2020, 8, 1), date(2020, 8, 31))
    dividend_event = next(e for e in events if e["trade_date"] == date(2020, 8, 7))
    assert dividend_event["dividend"] == pytest.approx(0.82)
    assert dividend_event["prev_close"] == pytest.approx(452.0)
    assert dividend_event["ex_factor"] == pytest.approx(452.0 / (452.0 - 0.82))


def test_split_and_dividend_on_same_day_combine_in_one_reference_price():
    chart = ChartData(
        symbol="XYZ", meta={},
        bars=[_bar(date(2026, 3, 2), 50.0), _bar(date(2026, 3, 3), 51.0)],
        splits=[(date(2026, 3, 3), 2.0)],
        dividends=[(date(2026, 3, 3), 1.0)],
    )
    ev = yp.adjustment_events(chart, date(2026, 1, 1), date(2026, 12, 31))[0]
    prev_raw = 100.0  # 50 × 2 (拆股前原始价)
    assert ev["ex_factor"] == pytest.approx(prev_raw / ((prev_raw - 1.0) / 2.0))


def test_events_outside_window_or_without_prev_close_are_skipped():
    chart = ChartData(
        symbol="XYZ", meta={},
        bars=[_bar(date(2026, 3, 2), 50.0), _bar(date(2026, 3, 3), 49.0)],
        dividends=[(date(2026, 3, 2), 0.5), (date(2026, 3, 3), 0.5)],
    )
    # 3-02 是首个 K 线日, 没有前收盘 → 跳过; 窗口外事件不返回
    assert [e["trade_date"] for e in yp.adjustment_events(chart, date(2026, 1, 1), date(2026, 12, 31))] == [
        date(2026, 3, 3)
    ]
    assert yp.adjustment_events(chart, date(2026, 4, 1), date(2026, 12, 31)) == []


# ---------------------------------------------------------------- 当日未定型 K 线


def test_unsettled_today_bar_is_dropped_before_close_settles():
    rows = [{"date": date(2026, 11, 6)}, {"date": date(2026, 11, 9)}]
    during = datetime(2026, 11, 9, 15, 59, tzinfo=NY_TZ)
    after = datetime(2026, 11, 9, 16, 20, tzinfo=NY_TZ)
    assert yp.drop_unsettled_today(rows, during) == [{"date": date(2026, 11, 6)}]
    assert yp.drop_unsettled_today(rows, after) == rows


# ---------------------------------------------------------------- Provider 批次与失败语义


class _FakeClient:
    def __init__(self, charts: dict[str, ChartData], fail: set[str] = frozenset(),
                 missing: set[str] = frozenset()) -> None:
        self.charts, self.fail, self.missing = charts, set(fail), set(missing)
        self.calls: list[tuple[str, date, date]] = []

    def get_chart(self, symbol, start, end):
        self.calls.append((symbol, start, end))
        if symbol in self.fail:
            raise YahooError(f"{symbol}: HTTP 503")
        if symbol in self.missing:
            raise YahooNotFoundError(f"{symbol}: not found")
        return self.charts[symbol]

    def close(self):
        pass


def _provider(client, tmp_path=None) -> yp.YahooUSProvider:
    return yp.YahooUSProvider(
        client=client, data_dir=tmp_path,
        clock=lambda: datetime(2026, 11, 9, 20, 0, tzinfo=NY_TZ),
    )


def _simple_chart(symbol: str) -> ChartData:
    return ChartData(symbol, {}, [_bar(date(2026, 11, 5), 10.0), _bar(date(2026, 11, 6), 11.0)])


def test_get_daily_returns_internal_contract_columns():
    client = _FakeClient({"AAPL": _split_chart()})
    df = _provider(client).get_daily(["AAPL"], datetime(2020, 8, 1), datetime(2020, 9, 30))
    assert set(df.columns) >= {"symbol", "date", "open", "high", "low", "close", "volume", "amount"}
    assert df.schema["date"] == pl.Date
    assert df.filter(pl.col("date") == date(2020, 8, 28))["close"][0] == pytest.approx(499.2)


def test_iter_daily_batches_and_reports_progress(monkeypatch):
    monkeypatch.setattr(yp, "_DAILY_BATCH", 2)
    symbols = ["AAA", "BBB", "CCC"]
    client = _FakeClient({s: _simple_chart(s) for s in symbols})
    progress: list[tuple[int, int]] = []
    frames = list(_provider(client).iter_daily(
        symbols, datetime(2026, 11, 1), datetime(2026, 11, 7), on_chunk_done=lambda c, t: progress.append((c, t)),
    ))
    assert [f.height for f in frames] == [4, 2]
    assert progress == [(1, 2), (2, 2)]


def test_partial_failure_and_unknown_symbol_are_skipped_not_fatal():
    client = _FakeClient({"AAA": _simple_chart("AAA")}, fail={"BBB"}, missing={"ZZZZ"})
    df = _provider(client).get_daily(["AAA", "BBB", "ZZZZ"], datetime(2026, 11, 1), datetime(2026, 11, 7))
    assert df["symbol"].unique().to_list() == ["AAA"]


def test_whole_batch_failure_raises_instead_of_publishing_partial_result():
    client = _FakeClient({}, fail={"AAA", "BBB"})
    with pytest.raises(ProviderRequestError):
        _provider(client).get_daily(["AAA", "BBB"], datetime(2026, 11, 1), datetime(2026, 11, 7))
    with pytest.raises(ProviderRequestError):
        _provider(client).get_adj_factors(["AAA", "BBB"], datetime(2026, 1, 1), datetime(2026, 11, 7))


def test_adj_factor_request_reaches_back_for_previous_close():
    client = _FakeClient({"AAPL": _split_chart()})
    df = _provider(client).get_adj_factors(["AAPL"], datetime(2020, 8, 31), datetime(2020, 9, 30))
    assert client.calls[0][1] < date(2020, 8, 31)
    assert df.columns == list(yp._ADJ_SCHEMA)
    assert df["ex_factor"].to_list() == pytest.approx([4.0])


def test_non_stock_asset_types_return_empty():
    client = _FakeClient({})
    provider = _provider(client)
    assert provider.get_daily(["SPY"], None, None, asset_type="etf").is_empty()
    assert provider.get_adj_factors(["SPY"], None, None, asset_type="index").is_empty()
    assert provider.get_instruments("etf") == []
    assert client.calls == []


# ---------------------------------------------------------------- 标的维表


def test_instruments_include_bundled_universe_and_user_extras(tmp_path):
    extra = tmp_path / yp.EXTRA_SYMBOLS_FILE
    extra.parent.mkdir(parents=True)
    extra.write_text("# 自选\nhood\nAAPL\nbad symbol\n600519.SH\n", encoding="utf-8")
    items = _provider(_FakeClient({}), tmp_path).get_instruments("stock")
    by_symbol = {i["symbol"]: i for i in items}
    assert {"AAPL", "MSFT", "BRK-B", "GOOGL", "HOOD"} <= set(by_symbol)
    assert len(items) >= 500
    assert by_symbol["AAPL"]["name"] == "Apple Inc."
    assert by_symbol["AAPL"]["exchange"] == "US"
    assert "600519.SH" not in by_symbol and "BAD SYMBOL" not in by_symbol
    assert len(by_symbol) == len(items)


# ---------------------------------------------------------------- 能力声明与注册


def test_declares_only_daily_and_adj_factor():
    provider = _provider(_FakeClient({}))
    assert set(provider.config.datasets) == {"daily", "adj_factor"}
    assert "realtime" not in provider.config.datasets
    assert "minute" not in provider.config.datasets
    result = provider.test_dataset("realtime")
    assert result["rows"] == 0 and "error" in result


def test_manifest_registers_through_loader():
    from app.data_providers.custom import loader

    manifest = loader.plugin_manifest("yahoo_us")
    assert manifest is not None
    assert manifest["entry"] == "app.plugins.yahoo_us.provider:YahooUSProvider"
    assert set(manifest.get("datasets") or []) == {"daily", "adj_factor"}
    loader._register_one_plugin(manifest)
    assert "yahoo_us" in loader._PLUGIN_STATUS
    assert loader.provider_has_dataset("yahoo_us", "daily")
    assert not loader.provider_has_dataset("yahoo_us", "realtime")
