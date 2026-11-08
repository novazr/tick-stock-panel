"""Yahoo Finance 美股数据源 provider (无需 Key)。

实现数据集:
  - daily        美股原始日K (不复权)
  - adj_factor   由拆股与分红事件推导的单事件除权因子
  - 标的维表     标普 500 + 纳指 100 (随插件打包的 universe.csv) + 用户追加代码

单位与口径 (CONTRIBUTING §3, 不可凭字段名推断):
  - Yahoo chart 的 OHLC 与成交量已按「之后发生的拆股」调整、未按分红调整。项目契约要求
    原始价, 因此按日期还原: 原始价 = Yahoo 价 × 该日之后全部拆股比例之积, 原始股数 =
    Yahoo 股数 ÷ 同一乘积。复权一律交给 adj_factor + indicators.pipeline。
  - volume 契约为「手」(1 手 = 100 股): floor(原始股数 / 100)。
  - amount: Yahoo 不提供成交额, 置 null, 不用价格 × 成交量伪造。
  - 日期: Yahoo 时间戳按 America/New_York 转为美东交易日。美股收盘 (16:00 ET) 前的当日
    K 线尚未定型, 不落盘。
  - ex_factor = 前收盘原始价 / 除权参考价, 参考价 = (P - D) / (1 + S), 与 A 股插件同一
    公式; D 为原始每股分红 (Yahoo 分红按之后的拆股调整过, 需同样还原), S = 拆股比例 - 1。
"""
from __future__ import annotations

import csv
import logging
import math
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path

import polars as pl

from app.data_providers.base import ProviderRequestError
from app.data_providers.normalizer import normalize_daily
from app.market import US_SYMBOL_PATTERN
from app.plugins.yahoo_us.client import (
    NY_TZ,
    ChartData,
    YahooClient,
    YahooError,
    YahooNotFoundError,
)

logger = logging.getLogger(__name__)

_DATASETS = ("daily", "adj_factor")
_UNIVERSE_FILE = Path(__file__).with_name("universe.csv")
# 用户追加的美股代码 (每行一个, # 开头为注释), 放在数据目录下
EXTRA_SYMBOLS_FILE = Path("user_data") / "yahoo_us_symbols.txt"
_DAILY_BATCH = 20
_DEFAULT_LOOKBACK_DAYS = 365
_ADJ_PREV_CLOSE_BACKDAYS = 10       # 取除权事件前收盘需要往前多拉的日历天
_MARKET_CLOSE_SETTLE = time(16, 15)  # 美东收盘后留 15 分钟让日K定型
_US_SYMBOL = re.compile(US_SYMBOL_PATTERN)

_ADJ_SCHEMA = {
    "symbol": pl.String, "trade_date": pl.Date, "ex_factor": pl.Float64,
    "dividend": pl.Float64, "bonus": pl.Float64, "allot": pl.Float64,
    "allot_price": pl.Float64, "prev_close": pl.Float64,
}


def availability() -> tuple[bool, str]:
    """公开接口无需 Key; 网络可达性在试拉时检查。"""
    return True, "ok"


@dataclass
class _YahooConfig:
    """轻量 config shim, 让 custom loader 的 provider_has_dataset 能识别本 provider。"""

    name: str = "yahoo_us"
    display_name: str = "Yahoo Finance（美股）"
    datasets: dict = field(default_factory=lambda: dict.fromkeys(_DATASETS))
    path: None = None
    builtin: bool = True


# ---------------------------------------------------------------- 纯函数


def _split_factor_after(splits: list[tuple[date, float]], day: date) -> float:
    """day 之后 (不含当日) 发生的全部拆股比例之积; Yahoo 当日价格已是拆股后口径。"""
    factor = 1.0
    for split_day, ratio in splits:
        if split_day > day:
            factor *= ratio
    return factor


def raw_daily_rows(chart: ChartData) -> list[dict]:
    """Yahoo 拆股调整口径 → 原始价、手。"""
    rows = []
    for bar in chart.bars:
        factor = _split_factor_after(chart.splits, bar["date"])
        shares = bar["volume"] / factor if bar["volume"] is not None else None
        rows.append({
            "symbol": chart.symbol,
            "date": bar["date"],
            "open": None if bar["open"] is None else bar["open"] * factor,
            "high": None if bar["high"] is None else bar["high"] * factor,
            "low": None if bar["low"] is None else bar["low"] * factor,
            "close": bar["close"] * factor,
            "volume": None if shares is None else float(math.floor(shares / 100.0)),
            "amount": None,
        })
    return rows


def adjustment_events(chart: ChartData, start: date, end: date) -> list[dict]:
    """拆股与分红事件 → 单事件除权因子 (窗口 [start, end] 内)。"""
    closes = {row["date"]: row["close"] for row in raw_daily_rows(chart)}
    days = sorted(closes)
    ratio_by_day: dict[date, float] = {}
    for day, ratio in chart.splits:
        ratio_by_day[day] = ratio_by_day.get(day, 1.0) * ratio
    dividend_by_day: dict[date, float] = {}
    for day, amount in chart.dividends:
        raw = amount * _split_factor_after(chart.splits, day)
        dividend_by_day[day] = dividend_by_day.get(day, 0.0) + raw

    out = []
    for day in sorted(set(ratio_by_day) | set(dividend_by_day)):
        if day < start or day > end:
            continue
        prev_days = [d for d in days if d < day]
        if not prev_days:
            logger.warning("Yahoo 除权因子: %s %s 缺少前收盘, 跳过", chart.symbol, day)
            continue
        prev_close = closes[prev_days[-1]]
        dividend = dividend_by_day.get(day, 0.0)
        bonus = ratio_by_day.get(day, 1.0) - 1.0
        if 1.0 + bonus <= 0:
            logger.warning("Yahoo 除权因子: %s %s 拆股比例异常, 跳过", chart.symbol, day)
            continue
        reference = (prev_close - dividend) / (1.0 + bonus)
        if reference <= 0:
            logger.warning(
                "Yahoo 除权因子: %s %s 参考价非正 (P=%s D=%s S=%s), 跳过",
                chart.symbol, day, prev_close, dividend, bonus,
            )
            continue
        out.append({
            "symbol": chart.symbol,
            "trade_date": day,
            "ex_factor": prev_close / reference,
            "dividend": dividend or None,
            "bonus": bonus or None,
            "allot": None,
            "allot_price": None,
            "prev_close": prev_close,
        })
    return out


def drop_unsettled_today(rows: list[dict], now_ny: datetime) -> list[dict]:
    """美东收盘定型前的当日 K 线不返回, 避免把盘中价当日线落盘。"""
    if now_ny.time() >= _MARKET_CLOSE_SETTLE:
        return rows
    today = now_ny.date()
    return [row for row in rows if row["date"] != today]


def load_universe(data_dir: Path | None) -> list[dict]:
    """打包的标普 500 + 纳指 100, 再追加用户代码文件中的代码 (去重, 校验格式)。"""
    items: dict[str, dict] = {}
    with _UNIVERSE_FILE.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            symbol = (row.get("symbol") or "").strip()
            if _US_SYMBOL.match(symbol):
                items[symbol] = {"symbol": symbol, "name": (row.get("name") or "").strip() or None}
    if data_dir is not None:
        extra = data_dir / EXTRA_SYMBOLS_FILE
        if extra.exists():
            for line in extra.read_text(encoding="utf-8").splitlines():
                symbol = line.split("#", 1)[0].strip().upper()
                if not symbol:
                    continue
                if not _US_SYMBOL.match(symbol):
                    logger.warning("美股代码文件中的 %r 格式不合规 (示例: AAPL / BRK-B), 已忽略", symbol)
                    continue
                items.setdefault(symbol, {"symbol": symbol, "name": None})
    return [items[s] for s in sorted(items)]


# ---------------------------------------------------------------- Provider


def _window(start_time: datetime | None, end_time: datetime | None) -> tuple[date, date]:
    end_d = (end_time or datetime.now(NY_TZ)).date()
    start_d = (start_time.date() if start_time else end_d - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
    return start_d, end_d


class YahooUSProvider:
    name = "yahoo_us"
    builtin = True

    def __init__(self, client: YahooClient | None = None, data_dir: Path | None = None,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.config = _YahooConfig()
        self._client = client
        self._data_dir = data_dir
        self._clock = clock or (lambda: datetime.now(NY_TZ))

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _get_client(self) -> YahooClient:
        if self._client is None:
            self._client = YahooClient()
        return self._client

    def _resolve_data_dir(self) -> Path | None:
        if self._data_dir is not None:
            return self._data_dir
        try:
            from app.config import settings
        except Exception:  # noqa: BLE001 — 维表追加文件可选, 配置不可用时只用打包清单
            return None
        return Path(settings.data_dir)

    # ---- 标的维表

    def get_instruments(self, asset_type: str = "stock") -> list[dict]:
        if asset_type != "stock":
            return []
        return [
            {
                "symbol": item["symbol"],
                "name": item["name"] or item["symbol"],
                "code": item["symbol"],
                "exchange": "US",
                "region": "US",
                "type": "stock",
                "ext": {},
            }
            for item in load_universe(self._resolve_data_dir())
        ]

    # ---- 日K

    def _charts(self, symbols: list[str], start_d: date, end_d: date,
                failures: list[str]) -> Iterator[ChartData]:
        client = self._get_client()
        for symbol in symbols:
            try:
                yield client.get_chart(symbol, start_d, end_d)
            except YahooNotFoundError as e:
                logger.warning("Yahoo 无此代码, 跳过: %s", e)
            except YahooError as e:
                logger.warning("Yahoo 请求失败: %s", e)
                failures.append(symbol)

    def iter_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> Iterator[pl.DataFrame]:
        """每批最多 20 只产出一帧; 某批全部请求失败时抛 ProviderRequestError, 不发布残缺结果。"""
        if not symbols or asset_type != "stock":
            return
        symbols = list(dict.fromkeys(symbols))
        start_d, end_d = _window(start_time, end_time)
        batches = [symbols[i:i + _DAILY_BATCH] for i in range(0, len(symbols), _DAILY_BATCH)]
        for index, batch in enumerate(batches):
            failures: list[str] = []
            rows: list[dict] = []
            for chart in self._charts(batch, start_d, end_d, failures):
                rows.extend(r for r in raw_daily_rows(chart) if start_d <= r["date"] <= end_d)
            if failures and len(failures) == len(batch):
                raise ProviderRequestError(f"Yahoo 日K整批请求失败: {failures[:5]}")
            rows = drop_unsettled_today(rows, self._clock())
            if on_chunk_done:
                on_chunk_done(index + 1, len(batches))
            if rows:
                df = normalize_daily(rows, source=self.name)
                if not df.is_empty():
                    yield df

    def get_daily(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        frames = list(self.iter_daily(symbols, start_time, end_time, asset_type, on_chunk_done))
        return pl.concat(frames, how="diagonal_relaxed") if frames else pl.DataFrame()

    # ---- 除权因子

    def get_adj_factors(
        self,
        symbols: list[str],
        start_time: datetime | None,
        end_time: datetime | None,
        asset_type: str = "stock",
        on_chunk_done: Callable[[int, int], None] | None = None,
    ) -> pl.DataFrame:
        if not symbols or asset_type != "stock":
            return pl.DataFrame(schema=_ADJ_SCHEMA)
        symbols = list(dict.fromkeys(symbols))
        start_d, end_d = _window(start_time, end_time)
        fetch_start = start_d - timedelta(days=_ADJ_PREV_CLOSE_BACKDAYS)
        failures: list[str] = []
        rows: list[dict] = []
        for index, chart in enumerate(self._charts(symbols, fetch_start, end_d, failures)):
            rows.extend(adjustment_events(chart, start_d, end_d))
            if on_chunk_done:
                on_chunk_done(index + 1, len(symbols))
        if failures and len(failures) == len(symbols):
            raise ProviderRequestError(f"Yahoo 除权事件整批请求失败: {failures[:5]}")
        if not rows:
            return pl.DataFrame(schema=_ADJ_SCHEMA)
        return (
            pl.DataFrame(rows, schema=_ADJ_SCHEMA)
            .unique(subset=["symbol", "trade_date"], keep="last")
            .sort(["symbol", "trade_date"])
        )

    # ---- 设置页试拉

    def test_dataset(self, dataset: str, symbols: list[str] | None = None) -> dict:
        if dataset not in _DATASETS:
            return {
                "provider": self.name, "dataset": dataset, "rows": 0,
                "error": f"Yahoo 美股插件未接入 {dataset} 数据集",
            }
        syms = [s for s in (symbols or []) if _US_SYMBOL.match(s)][:3] or ["AAPL"]
        now = datetime.now(NY_TZ)
        try:
            if dataset == "daily":
                df = self.get_daily(syms, now - timedelta(days=30), now)
            else:
                df = self.get_adj_factors(syms, now - timedelta(days=5 * 365), now)
        except (YahooError, ProviderRequestError) as e:
            return {"provider": self.name, "dataset": dataset, "rows": 0, "error": str(e)}
        head = df.head(5).to_dicts()
        for row in head:
            for key, value in list(row.items()):
                if isinstance(value, (date, datetime)):
                    row[key] = value.isoformat()
        return {
            "provider": self.name, "dataset": dataset, "rows": df.height,
            "columns": df.columns, "preview": head,
        }
