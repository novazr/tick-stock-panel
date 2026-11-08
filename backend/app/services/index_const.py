"""实时指数核心清单 — 产品级固定契约 (单一权威)。

指数展示层 (侧栏指数条 / 市场总览) 固定四只核心指数, 不开放配置:
- 数据源边界: TickFlow 与 fuyao 指数快照双源均完整覆盖, 无降级分歧;
- 后端消费方 (quote_service / overview / sector_monitor) 与前端 Layout
  统一引用此处, 不得各自维护副本。

按当前实例服务的市场 (``app.market.active_market``) 选择清单: A 股为四大指数;
美股以跟踪四大指数的 ETF 作为基准 (Yahoo 等免费源的指数代码不在标准代码格式内,
ETF 价格即市场通用报价)。消费方必须在调用时取清单, 不得在导入时缓存。

监控规则的指数标的不受此限 — quote_service 会把启用规则的指数并入显式拉取。
"""
from __future__ import annotations

from app.market import Market, active_market

CORE_INDEX_NAMES: dict[str, str] = {
    "000001.SH": "上证指数",
    "399001.SZ": "深证成指",
    "399006.SZ": "创业板指",
    "000680.SH": "科创综指",
}

CORE_INDEX_SYMBOLS: tuple[str, ...] = tuple(CORE_INDEX_NAMES.keys())

US_CORE_INDEX_NAMES: dict[str, str] = {
    "SPY": "标普500 (SPY)",
    "QQQ": "纳指100 (QQQ)",
    "DIA": "道琼斯 (DIA)",
    "IWM": "罗素2000 (IWM)",
}


def core_index_names(market: Market | None = None) -> dict[str, str]:
    """当前 (或指定) 市场的核心指数 {代码: 名称}, 顺序即展示顺序。"""
    market = market or active_market()
    return dict(US_CORE_INDEX_NAMES if market == "us" else CORE_INDEX_NAMES)


def core_index_symbols(market: Market | None = None) -> tuple[str, ...]:
    return tuple(core_index_names(market))
