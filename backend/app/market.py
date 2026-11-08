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
