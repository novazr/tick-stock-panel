"""组合回测: 最小交易单位 (美股 1 股) 与加仓 (金字塔) 规则。

加仓触发方式:
  - pyramid_add_step: 价格较上次成交价上涨达到该比例时盘中加仓
    (开盘已越过 → 开盘价成交, 盘中穿越 → 触发价成交);
  - pyramid_on_signal: 持仓期间买入信号再次出现时加仓 (按建仓口径成交);
    与 add_step 同时设置时, 还要求收盘价较上次成交价涨够 add_step 才加。
每次加仓金额 = 首次建仓金额 × pyramid_add_size, 受现金与总仓位上限钳制;
加仓后成本价为加权均价, 止损/止盈按均价计算。
"""
from __future__ import annotations

from datetime import date, timedelta

import polars as pl
import pytest

from app.backtest.engine import BacktestEngine, MatcherConfig

START = date(2024, 1, 1)


def _day(i: int, o: float, h: float, lo: float, c: float) -> dict:
    return {
        "symbol": "AAPL", "date": START + timedelta(days=i),
        "open": o, "high": h, "low": lo, "close": c,
        "volume": 100_000,
        "signal_limit_up": False, "signal_limit_down": False,
    }


def _masks(panel: pl.DataFrame, entry_days: set[int], exit_days: set[int] = frozenset()):
    dates = panel.get_column("date").to_list()
    entry = pl.Series([(dt - START).days in entry_days for dt in dates], dtype=pl.Boolean)
    exit_ = pl.Series([(dt - START).days in exit_days for dt in dates], dtype=pl.Boolean)
    return entry, exit_


def _run(panel: pl.DataFrame, entry_days: set[int], exit_days: set[int] = frozenset(), **cfg):
    entry, exit_ = _masks(panel, entry_days, exit_days)
    base = dict(matching="close_t", fees_pct=0, slippage_bps=0)
    base.update(cfg)
    return BacktestEngine(repo=None).simulate_portfolio(  # type: ignore[arg-type]
        panel, entry, exit_, MatcherConfig(**base),
    )


# ---------------------------------------------------------------- 最小交易单位


def _flat_panel() -> pl.DataFrame:
    return pl.DataFrame([_day(i, 10.0, 10.0, 10.0, 10.0) for i in range(3)])


def test_default_lot_size_is_100_shares():
    result = _run(_flat_panel(), {0}, initial_capital=1_050, max_positions=1)
    assert result.trades[0].shares == 100


def test_lot_size_one_share_for_us_market():
    result = _run(_flat_panel(), {0}, initial_capital=1_050, max_positions=1, lot_size=1)
    trade = result.trades[0]
    assert trade.shares == 105
    assert trade.lots == 105


def test_invalid_lot_size_rejected():
    with pytest.raises(ValueError):
        MatcherConfig(lot_size=0)


# ---------------------------------------------------------------- 按涨幅加仓


def _uptrend_panel() -> pl.DataFrame:
    return pl.DataFrame([
        _day(0, 10.0, 10.0, 10.0, 10.0),   # 收盘 10 建仓 2500 股 (100000 / 4)
        _day(1, 10.5, 11.2, 10.4, 11.1),   # 盘中触及 11.0 (+10%) → 触发价 11.0 加仓
        _day(2, 12.2, 12.5, 12.0, 12.3),   # 开盘 12.2 已越过 12.1 → 开盘价加仓
        _day(3, 13.5, 14.0, 13.4, 13.8),   # 已加满 2 次, 不再加
        _day(4, 14.0, 14.2, 13.9, 14.0),   # 期末按收盘 14.0 平仓
    ])


def test_add_on_gain_step_fills_at_trigger_or_gap_open():
    result = _run(
        _uptrend_panel(), {0},
        initial_capital=100_000, max_positions=4, lot_size=1,
        pyramid_max_adds=2, pyramid_add_step=0.10, pyramid_add_size=0.5,
    )
    assert result.stats["n_trades"] == 1
    trade = result.trades[0]
    first = 2500                     # 25000 / 10
    add1 = 12500 // 11.0             # 首仓金额 25000 × 0.5 / 11.0 → 1136
    add2 = 12500 // 12.2             # 1024
    assert trade.adds == 2
    assert trade.shares == first + add1 + add2
    cost = first * 10.0 + add1 * 11.0 + add2 * 12.2
    assert trade.entry_value == pytest.approx(cost, abs=0.01)
    assert trade.entry_price == pytest.approx(cost / trade.shares, abs=1e-4)
    assert trade.exit_price == 14.0
    assert trade.pnl_amount == pytest.approx(trade.shares * 14.0 - cost, abs=0.01)
    assert result.stats["execution"]["pyramid_adds"] == 2


def test_no_add_without_pyramid_settings():
    result = _run(_uptrend_panel(), {0}, initial_capital=100_000, max_positions=4, lot_size=1)
    trade = result.trades[0]
    assert trade.adds == 0
    assert trade.shares == 2500


def test_add_respects_exposure_cap():
    """总仓位上限 30%: 首仓 30000 已占满, 加仓被拦截并计数。"""
    result = _run(
        _uptrend_panel(), {0},
        initial_capital=100_000, max_positions=1, max_exposure_pct=0.30, lot_size=1,
        pyramid_max_adds=2, pyramid_add_step=0.10, pyramid_add_size=0.5,
    )
    trade = result.trades[0]
    assert trade.shares == 3000
    assert trade.adds == 0
    assert result.stats["execution"]["pyramid_blocked"] >= 1


def test_stop_loss_uses_average_cost_after_add():
    panel = pl.DataFrame([
        _day(0, 10.0, 10.0, 10.0, 10.0),
        _day(1, 10.5, 11.0, 10.5, 11.0),   # +10% 加仓 @11.0, 均价 ≈ 10.33
        _day(2, 10.4, 10.4, 9.7, 9.8),     # 止损线 = 均价 × 0.95 ≈ 9.81, 低点 9.7 触发
        _day(3, 9.8, 9.9, 9.7, 9.8),
    ])
    result = _run(
        panel, {0},
        initial_capital=100_000, max_positions=4, lot_size=1, stop_loss_pct=0.05,
        pyramid_max_adds=1, pyramid_add_step=0.10, pyramid_add_size=0.5,
    )
    trade = result.trades[0]
    assert trade.adds == 1
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_date == "2024-01-03"
    assert trade.exit_price == pytest.approx(trade.entry_price * 0.95, abs=1e-4)


# ---------------------------------------------------------------- 按信号加仓


def _signal_panel() -> pl.DataFrame:
    return pl.DataFrame([
        _day(0, 10.0, 10.0, 10.0, 10.0),
        _day(1, 10.2, 10.3, 10.1, 10.2),
        _day(2, 10.4, 10.6, 10.3, 10.5),   # 买入信号再次出现, 收盘 10.5 (+5%)
        _day(3, 10.6, 10.8, 10.5, 10.7),
        _day(4, 10.8, 11.0, 10.7, 11.0),
    ])


def test_add_when_entry_signal_repeats():
    result = _run(
        _signal_panel(), {0, 2},
        initial_capital=100_000, max_positions=4, lot_size=1,
        pyramid_max_adds=1, pyramid_on_signal=True, pyramid_add_size=1.0,
    )
    trade = result.trades[0]
    assert trade.adds == 1
    assert trade.shares == 2500 + 25000 // 10.5


def test_signal_add_requires_step_gain_when_both_set():
    """信号 + 涨幅同时设置: day2 收盘仅 +5%, 不足 10%, 不加仓。"""
    result = _run(
        _signal_panel(), {0, 2},
        initial_capital=100_000, max_positions=4, lot_size=1,
        pyramid_max_adds=1, pyramid_on_signal=True, pyramid_add_step=0.10, pyramid_add_size=1.0,
    )
    trade = result.trades[0]
    assert trade.adds == 0
    assert trade.shares == 2500


def test_repeated_signal_ignored_when_pyramid_off():
    result = _run(_signal_panel(), {0, 2}, initial_capital=100_000, max_positions=4, lot_size=1)
    assert result.trades[0].adds == 0
