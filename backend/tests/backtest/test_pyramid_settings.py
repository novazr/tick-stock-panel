"""策略层加仓参数解析: 策略文件常量为默认, 界面覆盖 (overrides) 优先, 越界钳制。"""
from types import SimpleNamespace

from app.backtest.strategy import resolve_pyramid_settings


def _strategy(**kw):
    base = dict(pyramid_max_adds=None, pyramid_add_step=None, pyramid_add_size=None, pyramid_on_signal=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_off_by_default():
    assert resolve_pyramid_settings({}, _strategy()) == {
        "pyramid_max_adds": 0, "pyramid_add_step": None,
        "pyramid_add_size": 0.5, "pyramid_on_signal": False,
    }


def test_strategy_constants_used():
    s = _strategy(pyramid_max_adds=2, pyramid_add_step=0.1, pyramid_add_size=1.0)
    got = resolve_pyramid_settings({}, s)
    assert got["pyramid_max_adds"] == 2
    assert got["pyramid_add_step"] == 0.1
    assert got["pyramid_add_size"] == 1.0
    assert got["pyramid_on_signal"] is False


def test_overrides_win_and_values_are_clamped():
    s = _strategy(pyramid_max_adds=2, pyramid_add_step=0.1)
    got = resolve_pyramid_settings(
        {"pyramid_max_adds": 99, "pyramid_add_step": -0.05, "pyramid_add_size": 0, "pyramid_on_signal": True},
        s,
    )
    assert got["pyramid_max_adds"] == 10
    assert got["pyramid_add_step"] == 0.05     # 负号按幅度处理
    assert got["pyramid_add_size"] == 0.05     # 下限
    assert got["pyramid_on_signal"] is True


def test_override_can_turn_off_step():
    s = _strategy(pyramid_max_adds=2, pyramid_add_step=0.1, pyramid_on_signal=True)
    got = resolve_pyramid_settings({"pyramid_add_step": None}, s)
    assert got["pyramid_add_step"] is None
    assert got["pyramid_on_signal"] is True


def test_max_adds_without_trigger_is_disabled():
    got = resolve_pyramid_settings({"pyramid_max_adds": 2}, _strategy())
    assert got["pyramid_max_adds"] == 0


def test_trade_dict_includes_adds():
    from app.backtest.engine import TradeRecord
    from app.backtest.strategy import StrategyBacktestService

    t = TradeRecord(symbol="AAPL", entry_date="2024-01-01", exit_date="2024-01-05",
                    entry_price=10.0, exit_price=11.0, pnl_pct=0.1, duration=4,
                    exit_reason="end", adds=2)
    assert StrategyBacktestService._trade_to_dict(t)["adds"] == 2
