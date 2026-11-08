/**
 * 涨跌配色随实例市场切换:A 股红涨绿跌,美股绿涨红跌。
 *
 * CSS 侧通过 html[data-market="us"] 交换 --bull / --bear;
 * 画布图表 (ECharts / lightweight-charts) 无法读 CSS 类,调用 marketPalette() 取色。
 * 市场值由 Layout 在拿到 /api/settings 后写入,并缓存到 localStorage,
 * 下次打开页面时首屏即可用正确配色。
 */

export type MarketCode = 'cn' | 'us'

const STORAGE_KEY = 'tsp.market'

const RED = { solid: '#F04438', muted: '#C74040', rgb: '240,68,56' }
const GREEN = { solid: '#12B76A', muted: '#2D9B65', rgb: '18,183,106' }

export interface MarketPalette {
  /** 上涨主色 (K 线实体) */
  bull: string
  /** 下跌主色 */
  bear: string
  /** 上涨柔和色 (EChartsCandlestick / 分时线) */
  bullMuted: string
  bearMuted: string
  /** 上涨 / 下跌带透明度,用于成交量柱等 */
  bullAlpha: (alpha: number) => string
  bearAlpha: (alpha: number) => string
}

function build(up: typeof RED, down: typeof RED): MarketPalette {
  return {
    bull: up.solid,
    bear: down.solid,
    bullMuted: up.muted,
    bearMuted: down.muted,
    bullAlpha: (a) => `rgba(${up.rgb},${a})`,
    bearAlpha: (a) => `rgba(${down.rgb},${a})`,
  }
}

const CN_PALETTE = build(RED, GREEN)
const US_PALETTE = build(GREEN, RED)

export function paletteFor(market: MarketCode | null | undefined): MarketPalette {
  return market === 'us' ? US_PALETTE : CN_PALETTE
}

export function currentMarket(): MarketCode {
  if (typeof document !== 'undefined' && document.documentElement.dataset.market === 'us') return 'us'
  return 'cn'
}

export function marketPalette(): MarketPalette {
  return paletteFor(currentMarket())
}

/** 写入 html[data-market] 并缓存;未知值按 A 股处理。 */
export function applyMarket(market: MarketCode | null | undefined): void {
  const value: MarketCode = market === 'us' ? 'us' : 'cn'
  if (typeof document !== 'undefined') document.documentElement.dataset.market = value
  try {
    localStorage.setItem(STORAGE_KEY, value)
  } catch {
    /* 隐私模式等场景忽略 */
  }
}

/** 应用启动时调用:用上次缓存的市场先行设置,避免首屏闪一次反向配色。 */
export function restoreMarket(): void {
  let cached: string | null = null
  try {
    cached = localStorage.getItem(STORAGE_KEY)
  } catch {
    cached = null
  }
  if (cached === 'us' || cached === 'cn') applyMarket(cached)
}
