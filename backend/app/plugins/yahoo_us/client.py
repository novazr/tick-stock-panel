"""Yahoo Finance 公开 chart 接口客户端 (无需 Key)。

只负责请求、限速、重试和把响应解析成「拆股调整后」的原始字段; 单位、原始价还原、
除权因子推导在 provider 中完成。
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
NY_TZ = ZoneInfo("America/New_York")
# 浏览器 UA: 无 UA 的请求会被 Yahoo 直接拒绝
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
MIN_INTERVAL_S = 0.25        # 请求间隔下限 (约 4 次/秒)
MAX_RETRIES = 3
RETRY_STATUS = {429, 500, 502, 503, 504}


class YahooError(RuntimeError):
    """请求失败 (网络、限流重试耗尽、响应结构异常)。"""


class YahooNotFoundError(YahooError):
    """接口明确表示没有该代码 (退市、改名或拼写错误)。"""


@dataclass
class ChartData:
    """单标的 chart 响应。价格与成交量是 Yahoo 口径: 已按拆股调整, 未按分红调整。"""

    symbol: str
    meta: dict
    bars: list[dict]                                   # date/open/high/low/close/volume
    splits: list[tuple[date, float]] = field(default_factory=list)      # (除权日, 新股数/旧股数)
    dividends: list[tuple[date, float]] = field(default_factory=list)   # (除息日, 拆股调整后每股分红)


def ny_date(epoch_s: int | float) -> date:
    """Yahoo 时间戳 (UTC 秒) → 美东交易日期。"""
    return datetime.fromtimestamp(float(epoch_s), NY_TZ).date()


def _f(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_chart(symbol: str, payload: dict) -> ChartData:
    chart = (payload or {}).get("chart") or {}
    error = chart.get("error")
    if error:
        code = str(error.get("code") or "")
        message = f"{symbol}: {error.get('description') or code}"
        if code.lower() in {"not found", "notfound"}:
            raise YahooNotFoundError(message)
        raise YahooError(message)
    results = chart.get("result") or []
    if not results:
        raise YahooError(f"{symbol}: chart 响应缺少 result")
    result = results[0]
    timestamps = result.get("timestamp") or []
    quotes = ((result.get("indicators") or {}).get("quote") or [{}])[0]
    bars: list[dict] = []
    for i, ts in enumerate(timestamps):
        row = {k: _f((quotes.get(k) or [None] * len(timestamps))[i])
               for k in ("open", "high", "low", "close", "volume")}
        if row["close"] is None:
            continue  # Yahoo 用 null 占位的非交易时段
        row["date"] = ny_date(ts)
        bars.append(row)
    events = result.get("events") or {}
    splits = []
    for ev in (events.get("splits") or {}).values():
        num, den = _f(ev.get("numerator")), _f(ev.get("denominator"))
        if ev.get("date") is not None and num and den:
            splits.append((ny_date(ev["date"]), num / den))
    dividends = []
    for ev in (events.get("dividends") or {}).values():
        amount = _f(ev.get("amount"))
        if ev.get("date") is not None and amount:
            dividends.append((ny_date(ev["date"]), amount))
    return ChartData(
        symbol=symbol,
        meta=result.get("meta") or {},
        bars=bars,
        splits=sorted(splits),
        dividends=sorted(dividends),
    )


class YahooClient:
    """线程安全: 共享 httpx.Client, 请求间隔由锁串行控制。"""

    def __init__(self, timeout: float = 20.0, base_url: str = BASE_URL) -> None:
        self._base_url = base_url
        self._http = httpx.Client(timeout=timeout, headers={"User-Agent": _USER_AGENT})
        self._lock = threading.Lock()
        self._last_request = 0.0

    def close(self) -> None:
        self._http.close()

    def _throttle(self) -> None:
        with self._lock:
            wait = self._last_request + MIN_INTERVAL_S - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get_chart(self, symbol: str, start: date, end: date) -> ChartData:
        """日线 + 拆股/分红事件; end 为闭区间 (美东日期)。"""
        period1 = int(datetime(start.year, start.month, start.day, tzinfo=NY_TZ).timestamp())
        period2 = int(datetime(end.year, end.month, end.day, 23, 59, tzinfo=NY_TZ).timestamp())
        params = {
            "period1": period1,
            "period2": period2,
            "interval": "1d",
            "events": "div,splits",
            "includeAdjustedClose": "false",
        }
        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES + 1):
            self._throttle()
            try:
                resp = self._http.get(self._base_url + symbol, params=params)
            except httpx.HTTPError as e:
                last_error = e
            else:
                if resp.status_code == 404:
                    try:
                        return parse_chart(symbol, resp.json())
                    except YahooError:
                        raise
                    except ValueError as e:
                        raise YahooNotFoundError(f"{symbol}: HTTP 404") from e
                if resp.status_code in RETRY_STATUS:
                    last_error = YahooError(f"{symbol}: HTTP {resp.status_code}")
                elif resp.status_code != 200:
                    raise YahooError(f"{symbol}: HTTP {resp.status_code}")
                else:
                    try:
                        return parse_chart(symbol, resp.json())
                    except ValueError as e:
                        raise YahooError(f"{symbol}: 响应不是 JSON") from e
            if attempt < MAX_RETRIES:
                time.sleep(2 ** (attempt + 1))
        raise YahooError(f"{symbol}: 重试 {MAX_RETRIES} 次仍失败: {last_error}")
