"""标的所属市场识别: 判断一个标准代码属于 A 股还是美股的唯一入口。

代码格式契约:
  - A 股: 6 位数字 + 交易所后缀, 如 ``600519.SH`` / ``000001.SZ`` / ``830799.BJ``
  - 美股: 交易代码大写, 类别股用连字符, 如 ``AAPL`` / ``BRK-B`` (与 Yahoo 一致,
    避免与 A 股的点号后缀混淆)

无法识别的代码返回 ``None``, 由调用方按自身语义明确处理, 不在这里猜测。
"""
from __future__ import annotations

import re
from typing import Literal

Market = Literal["cn", "us"]

CN_SYMBOL_PATTERN = r"^\d{6}\.(SH|SZ|BJ)$"
US_SYMBOL_PATTERN = r"^[A-Z]{1,5}(-[A-Z]{1,2})?$"

_CN_SYMBOL = re.compile(CN_SYMBOL_PATTERN)
_US_SYMBOL = re.compile(US_SYMBOL_PATTERN)


def market_of(symbol: str | None) -> Market | None:
    """返回标的所属市场; 非标准格式 (含小写、空白、未知后缀) 返回 None。"""
    if not isinstance(symbol, str):
        return None
    if _CN_SYMBOL.match(symbol):
        return "cn"
    if _US_SYMBOL.match(symbol):
        return "us"
    return None


def is_us_symbol(symbol: str | None) -> bool:
    return market_of(symbol) == "us"


def active_market() -> Market:
    """当前实例服务的市场: 跟随日K数据源 (标的维表同样跟随日K源)。

    插件以类属性 ``market = "us"`` 声明所服务的市场; 未声明、TickFlow 或任何读取
    失败一律视为 A 股, 与改造前行为一致。
    """
    try:
        from app.services import preferences

        name = preferences.get_daily_data_provider()
        if name == "tickflow":
            return "cn"
        from app.data_providers import custom as custom_sources

        if not custom_sources.is_custom_provider(name):
            return "cn"
        market = getattr(custom_sources.get_provider(name), "market", "cn")
    except Exception:  # noqa: BLE001 — 市场判定用于展示层选择, 失败回落 A 股原行为
        return "cn"
    return "us" if market == "us" else "cn"


def lot_size(market: Market | None = None) -> int:
    """最小交易单位 (股): A 股 100 股一手, 美股 1 股起买。未指定市场时跟随实例市场。"""
    return 1 if (market or active_market()) == "us" else 100
