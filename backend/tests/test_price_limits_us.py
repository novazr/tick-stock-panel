"""美股没有日内涨跌幅限制: 四条涨跌停路径 (标量 / polars / numpy / 维表 API) 对美股
都必须给出「无限制」, 且 A 股结果与改造前逐值一致。

若美股误套 A 股主板 ±10%, 大涨日会被当成「涨停买不进」, 回测与信号静默出错。
"""
from __future__ import annotations

from datetime import date

import numpy as np
import polars as pl
import pytest

from app.api import kline
from app.backtest import minute_replay
from app.backtest.matrix import load_market_data_matrix_from_parquet
from app.indicators import pipeline
from app.price_limits import (
    board_limit_pct,
    is_no_limit_day,
    no_limit_window_days,
    numpy_limit_price,
    numpy_price_limit_matrix,
    polars_limit_price,
    polars_price_limit_pct,
    price_limit_pct,
)


@pytest.mark.parametrize("symbol", ["AAPL", "BRK-B", "QQQ"])
def test_scalar_rules_have_no_limit_for_us(symbol):
    assert board_limit_pct(symbol) is None
    assert price_limit_pct(symbol, date(2026, 7, 3), is_risk_warning=True) is None
    assert no_limit_window_days(symbol, date(2026, 1, 2)) == 0
    assert not is_no_limit_day(symbol, date(2026, 1, 2), date(2026, 1, 5))


def test_scalar_rules_unchanged_for_cn():
    assert price_limit_pct("600001.SH", date(2026, 7, 3), is_risk_warning=True) == 0.05
    assert price_limit_pct("300001.SZ", date(2026, 7, 3)) == 0.20
    assert price_limit_pct("830001.BJ", date(2026, 7, 3)) == 0.30


def test_polars_limit_is_null_for_us_and_unchanged_for_cn():
    frame = pl.DataFrame({
        "symbol": ["AAPL", "600001.SH", "BRK-B", "300001.SZ"],
        "date": [date(2026, 7, 3)] * 4,
        "st": [False, True, False, False],
        "prev": [200.0, 10.0, 450.0, 20.0],
    })
    out = frame.with_columns(
        polars_price_limit_pct(pl.col("symbol"), pl.col("date"), pl.col("st")).alias("pct"),
    ).with_columns(
        polars_limit_price(pl.col("prev"), pl.col("pct"), up=True).alias("up"),
        polars_limit_price(pl.col("prev"), pl.col("pct"), up=False).alias("down"),
    )
    assert out["pct"].to_list() == [None, 0.05, None, 0.20]
    assert out["up"].to_list()[0] is None and out["up"].to_list()[2] is None
    assert out["down"].to_list()[0] is None and out["down"].to_list()[2] is None
    assert out["up"][1] == pytest.approx(10.50)
    assert out["up"][3] == pytest.approx(24.00)


def test_numpy_limit_matrix_and_prices_for_mixed_markets():
    dates = [date(2020, 8, 21), date(2026, 7, 3), date(2026, 7, 6)]
    matrix = numpy_price_limit_matrix(dates, ["AAPL", "600001.SH"], ["Apple", "*ST主板"])
    assert np.isnan(matrix[:, 0]).all()
    np.testing.assert_allclose(matrix[:, 1], np.array([0.05, 0.05, 0.10], dtype=np.float32))

    prices = numpy_limit_price(np.array([200.0, 10.0]), matrix[1].astype(np.float64), up=True)
    assert np.isnan(prices[0])
    assert prices[1] == pytest.approx(10.50)


def test_daily_pipeline_never_marks_us_limit_up():
    rows = pl.DataFrame({
        "symbol": ["AAPL", "AAPL"],
        "date": [date(2026, 7, 17), date(2026, 7, 20)],
        "open": [200.0, 230.0],
        "high": [200.0, 230.0],
        "low": [200.0, 230.0],
        "close": [200.0, 230.0],
        "raw_close": [200.0, 230.0],
        "raw_high": [200.0, 230.0],
    })
    result = pipeline.compute_limit_signals(
        rows,
        pl.DataFrame({"symbol": ["AAPL"], "name": ["Apple Inc."]}),
        needed={"consecutive_limit_ups"},
    )
    assert result["limit_up_price"].to_list() == [None, None]
    assert result["limit_down_price"].to_list() == [None, None]
    assert result["consecutive_limit_ups"].to_list() == [0, 0]


def test_matrix_backtest_does_not_lock_us_stock_on_big_up_day(tmp_path):
    root = tmp_path / "market"
    closes = [(date(2026, 7, 16), 200.0), (date(2026, 7, 17), 230.0), (date(2026, 7, 20), 260.0)]
    for trade_date, close in closes:
        partition = root / f"date={trade_date.isoformat()}"
        partition.mkdir(parents=True)
        pl.DataFrame({
            "symbol": ["AAPL"],
            "date": [trade_date],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "raw_close": [close],
            "volume": [1000.0],
        }).write_parquet(partition / "part.parquet")

    market = load_market_data_matrix_from_parquet(
        root,
        closes[0][0],
        closes[-1][0],
        field_columns={"raw_close", "price_limit_pct"},
        instruments=pl.DataFrame({"symbol": ["AAPL"], "name": ["Apple Inc."]}),
        cache_root=tmp_path / "cache",
    )
    assert np.isnan(market.field("price_limit_pct")[:, 0]).all()
    assert market.limit_up_locked[:, 0].tolist() == [0, 0, 0]
    assert market.limit_down_locked[:, 0].tolist() == [0, 0, 0]


class _UsInstrumentRepo:
    def get_instruments_asset(self, asset_type: str) -> pl.DataFrame:
        return pl.DataFrame({"symbol": ["AAPL"], "listing_date": ["1980-12-12"]})


def test_kline_limit_info_reports_no_limit_for_us():
    info = kline._get_price_limit_info(
        _UsInstrumentRepo(), "AAPL", date(2026, 7, 20), "stock", "Apple Inc.",
    )
    assert info is not None
    assert info["rate"] is None
    assert info["no_limit"] is True
    assert info["limit_up"] is None and info["limit_down"] is None


def test_minute_replay_limit_check_skips_us():
    # 美股: 无论分钟价涨多少都不拒买
    assert not minute_replay._blocked_by_limit_up("AAPL", date(2026, 7, 20), "Apple Inc.", 200.0, 260.0)
    # A 股: 主板 10% 封板仍拒买
    assert minute_replay._blocked_by_limit_up("600001.SH", date(2026, 7, 20), "普通股", 10.0, 11.0)
    assert not minute_replay._blocked_by_limit_up("600001.SH", date(2026, 7, 20), "普通股", 10.0, 10.5)
