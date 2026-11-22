import { useEffect, useMemo, useState } from 'react'
import { useChartTheme } from '@/lib/theme'
import { plotPaneHeights } from '@/lib/chart-layout'
import { FinancialPlot } from '@/components/charts/FinancialPlot'
import type { KlineRow, LevelSeries } from '@/lib/api'
import { fmtBigNum, fmtPrice, fmtVolume, priceColorClass } from '@/lib/format'
import { currentMarket } from '@/lib/market-palette'
import {
  ANALYSIS_LABEL_BAND_PX,
  LEVEL_GROUPS,
  buildAnalysisChartModel,
  hitTestAnalysis,
  levelKey,
  type ChartMarker,
  type ChartRange,
  type LevelType,
  type PriceLevel,
} from './analysis-chart-model'

/**
 * 个股分析专用日 K 图表（TradingView lightweight-charts）。
 *
 * 与 StockDailyKChart/LightweightDaily 刻意不复用业务外壳:
 *   - 那套图表面向「行情浏览」,强调全套指标副图(MA/MACD/KDJ/BOLL)、涨停标记等；
 *   - 本图表面向「分析决策」,核心是【关键价位】(压力/支撑/密集区/枢轴/前高前低),
 *     通过开关按钮控制各价位组的显隐,布局更简洁(主图 + 成交量即可)。
 *
 * 渲染层由 FinancialPlot 承担；价位线、通道曲线、右侧标签和十字线命中判断
 * 集中在 analysis-chart-model 中，可脱离画布单测。
 *
 * 预留接口(类型已定义，接入方式已支持):
 *   - markers: 日期标记点(新闻/暴雷/利好 → 图内文字标签)
 *   - ranges:  区间高亮(事件区间 → 背景色块)
 *   - onDateClick: 点击某根 K 线回调
 */

export type { ChartMarker, ChartRange, LevelType, PriceLevel } from './analysis-chart-model'
export { LEVEL_GROUPS } from './analysis-chart-model'

interface Props {
  rows: KlineRow[]
  levels?: Record<LevelType, PriceLevel[]>
  /** 带状曲线指标(布林带/Keltner/ATR)的每日序列 —— 画成跟随时间漂移的曲线 */
  series?: LevelSeries
  /** series 数据对应的日期数组(与 series 各数组对齐) */
  seriesDates?: string[]
  /** 默认开启的价位组 */
  defaultLevelTypes?: LevelType[]
  /** 预留:新闻/暴雷/利好日期标记 */
  markers?: ChartMarker[]
  /** 预留:事件区间高亮 */
  ranges?: ChartRange[]
  /** 预留:点击某根 K 线 */
  onDateClick?: (date: string) => void
  /** 默认可见的 K 线根数; 'all' = 铺满全部已加载数据。缺省为最近约 6 个月 */
  visibleBars?: number | 'all'
  /** 切换标的时重置视口/悬浮状态(通常传 symbol) */
  scopeKey?: string
  height?: number
  className?: string
}

/** 默认显示最近 6 个月 ≈ 120 个交易日 */
const VISIBLE_BARS = 120

export function AnalysisKChart({
  rows,
  levels,
  series,
  seriesDates,
  defaultLevelTypes = ['sr', 'pivot', 'keltner_s'],
  markers,
  ranges,
  onDateClick,
  visibleBars = VISIBLE_BARS,
  scopeKey,
  height = 460,
  className,
}: Props) {
  const [activeTypes, setActiveTypes] = useState<Set<LevelType>>(() => new Set(defaultLevelTypes))
  /** 枢轴点显示到第几档:1=只P+R1/S1, 2=到R2/S2, 3=全档(R3/S3) */
  const [pivotRank, setPivotRank] = useState<1 | 2 | 3>(1)
  /** 双向联动高亮: mouse 悬浮价位/面板行。值为 levelKey 或曲线组 key, null=无高亮 */
  const [hoveredKey, setHoveredKey] = useState<string | null>(null)
  /** 十字线所在交易日 (任意副图均生效); null=不显示行情浮窗 */
  const [hoverDate, setHoverDate] = useState<string | null>(null)
  /** 行情浮窗停靠侧: 指针在图表左半时靠右, 反之靠左, 避免盖住正在看的 K 线 */
  const [cardSide, setCardSide] = useState<'left' | 'right'>('left')

  const model = useMemo(() => buildAnalysisChartModel({
    rows, levels, series, seriesDates, activeTypes, pivotRank, hoveredKey, markers, ranges,
  }), [rows, levels, series, seriesDates, activeTypes, pivotRank, hoveredKey, markers, ranges])

  // 图表模型只保留 OHLCV; 成交额按日期从原始行取, 供行情浮窗展示
  const amountByDate = useMemo(() => {
    const map = new Map<string, number>()
    for (const row of rows) {
      const amount = Number(row.amount)
      if (row.amount != null && Number.isFinite(amount)) map.set(String(row.date).slice(0, 10), amount)
    }
    return map
  }, [rows])

  const paneHeights = useMemo(() => plotPaneHeights(height, 1), [height])
  const scope = `${scopeKey ?? ''}:${model.rows[0]?.date ?? ''}:${model.rows.length}`

  // 切股 / 区间变化后清掉上一份数据的悬浮高亮
  useEffect(() => { setHoveredKey(null); setHoverDate(null) }, [scope])

  // 关闭价位组后,被关掉的点位不应继续高亮
  useEffect(() => {
    setHoveredKey(previous => previous != null && !model.hoverKeys.has(previous) ? null : previous)
  }, [model.hoverKeys])

  const toggleType = (type: LevelType) => {
    setActiveTypes(previous => {
      const next = new Set(previous)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  return (
    <div className={className}>
      {/* 价位开关按钮组 */}
      {levels && (
        <div className="flex flex-wrap items-center gap-1.5 mb-2">
          <span className="text-[10px] text-muted mr-1">关键价位</span>
          {LEVEL_GROUPS.map(group => {
            const active = activeTypes.has(group.key)
            // 枢轴点数量按当前档位过滤显示;其他组显示原始数量
            const raw = levels[group.key] ?? []
            const count = group.key === 'pivot'
              ? raw.filter(point => point.rank === undefined || point.rank <= pivotRank).length
              : raw.length
            return (
              <button
                key={group.key}
                onClick={() => toggleType(group.key)}
                disabled={raw.length === 0}
                title={`${group.label} (${count} 个)`}
                className={`inline-flex items-center gap-1 h-6 px-2 rounded-md text-[10px] font-medium border transition-all disabled:opacity-30 disabled:cursor-not-allowed ${
                  active
                    ? 'text-foreground'
                    : 'text-muted bg-base/40 border-border/30 hover:border-border/60'
                }`}
                style={active ? { borderColor: group.color + '66', backgroundColor: group.color + '1a' } : undefined}
              >
                <span className="h-1.5 w-1.5 rounded-full" style={{ backgroundColor: active ? group.color : '#52525B' }} />
                {group.label}
                <span className="opacity-50">{count}</span>
              </button>
            )
          })}

          {/* 枢轴点档位选择器 —— 仅当枢轴点开启时显示 */}
          {activeTypes.has('pivot') && (levels.pivot?.length ?? 0) > 0 && (
            <div className="inline-flex items-center gap-0.5 ml-1 pl-2 border-l border-border/40">
              <span className="text-[10px] text-muted mr-1">档位</span>
              {([1, 2, 3] as const).map(rank => (
                <button
                  key={rank}
                  onClick={() => setPivotRank(rank)}
                  title={rank === 1 ? 'P + R1/S1(3 个)' : rank === 2 ? '到 R2/S2(5 个)' : '全档 R3/S3(7 个)'}
                  className={`h-6 px-2 rounded-md text-[10px] font-mono border transition-all ${
                    pivotRank === rank
                      ? 'bg-[#8B5CF6]/15 border-[#8B5CF6]/40 text-[#c4b5fd]'
                      : 'text-muted bg-base/40 border-border/30 hover:border-border/60'
                  }`}
                >
                  {rank}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 图表:右侧预留带(rightOffsetPixels)显示价位/曲线标签,不压蜡烛 */}
      <div
        className="relative"
        onMouseMove={event => {
          const rect = event.currentTarget.getBoundingClientRect()
          const next = event.clientX - rect.left < rect.width / 2 ? 'right' : 'left'
          setCardSide(previous => previous === next ? previous : next)
        }}
      >
      <FinancialPlot
        scope={scope}
        series={model.series}
        height={height}
        paneHeights={paneHeights}
        pricePrecision={2}
        visibleBars={visibleBars}
        rightOffsetPixels={ANALYSIS_LABEL_BAND_PX}
        annotations={model.annotations}
        paneTitles={['', '成交量']}
        onSelect={date => onDateClick?.(date)}
        onHover={date => setHoverDate(previous => previous === date ? previous : date)}
        onCrosshairMove={point => {
          if (!point) { setHoveredKey(null); return }
          const index = model.dateIndex.get(point.time) ?? -1
          const next = index < 0 ? null : hitTestAnalysis(model, point.price, point.pixelsPerPrice, index)
          setHoveredKey(previous => previous === next ? previous : next)
        }}
      />
      <QuoteHoverCard
        rows={model.rows}
        index={hoverDate == null ? -1 : model.dateIndex.get(hoverDate) ?? -1}
        amount={hoverDate == null ? undefined : amountByDate.get(hoverDate)}
        side={cardSide}
      />
      </div>

      {/* 价位统计面板:把当前开启的点位按"压力 / 支撑"结构化列出 */}
      {levels && (
        <LevelOverview
          levels={levels}
          activeTypes={activeTypes}
          pivotRank={pivotRank}
          close={model.rows.length ? model.rows[model.rows.length - 1].close : undefined}
          hoveredKey={hoveredKey}
          onHover={setHoveredKey}
        />
      )}
    </div>
  )
}

// ===== 行情浮窗(十字线所在交易日的开高低收/涨跌/量额) =====

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六']

function weekdayLabel(date: string): string {
  const [year, month, day] = date.slice(0, 10).split('-').map(Number)
  if (!year || !month || !day) return ''
  // 按日历日期取星期, 不经过时区换算
  return `星期${WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()]}`
}

type QuoteRow = Pick<KlineRow, 'date' | 'open' | 'high' | 'low' | 'close' | 'volume'>

function QuoteHoverCard({ rows, index, amount, side }: {
  rows: QuoteRow[]
  index: number
  amount?: number
  side: 'left' | 'right'
}) {
  const row = index >= 0 ? rows[index] : undefined
  if (!row) return null
  // 涨跌以前一交易日收盘为基准; 首根 K 线没有基准, 涨跌留空
  const prevClose = index > 0 ? rows[index - 1].close : null
  const change = prevClose != null ? row.close - prevClose : null
  const changePct = change != null && prevClose ? change / prevClose * 100 : null
  const vs = (value: number) => prevClose != null ? priceColorClass(value - prevClose) : 'text-foreground'
  const signed = (value: number | null, suffix = '') =>
    value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(2)}${suffix}`
  const items: Array<[string, string, string]> = [
    ['开盘', fmtPrice(row.open), vs(row.open)],
    ['最高', fmtPrice(row.high), vs(row.high)],
    ['最低', fmtPrice(row.low), vs(row.low)],
    ['收盘', fmtPrice(row.close), vs(row.close)],
    ['涨跌额', signed(change), priceColorClass(change)],
    ['涨跌幅', signed(changePct, '%'), priceColorClass(change)],
    ['成交量', fmtVolume(row.volume), 'text-foreground'],
    // 美股数据源不提供成交额, 后端按均价估算, 这里如实标注
    [currentMarket() === 'us' ? '成交额(估)' : '成交额', amount == null ? '—' : fmtBigNum(amount), 'text-foreground'],
  ]
  return (
    <div
      data-testid="quote-hover-card"
      className="pointer-events-none absolute top-2 z-10 min-w-[168px] rounded-md border border-border bg-surface/95 px-2.5 py-2 text-xs shadow-lg"
      style={side === 'left' ? { left: 8 } : { right: ANALYSIS_LABEL_BAND_PX + 72 }}
    >
      <div className="mb-1 font-mono font-semibold text-foreground">{row.date.slice(0, 10)} {weekdayLabel(row.date)}</div>
      {items.map(([label, value, color]) => (
        <div key={label} className="flex items-center justify-between gap-4 leading-5">
          <span className="text-secondary">{label}</span>
          <span className={`font-mono font-medium tabular-nums ${color}`}>{value}</span>
        </div>
      ))}
    </div>
  )
}

// ===== 价位统计面板(图表下方,结构化文本展示) =====
function LevelOverview({
  levels, activeTypes, pivotRank, close, hoveredKey, onHover,
}: {
  levels: Record<LevelType, PriceLevel[]>
  activeTypes: Set<LevelType>
  pivotRank: 1 | 2 | 3
  close?: number
  hoveredKey: string | null
  onHover: (key: string | null) => void
}) {
  const theme = useChartTheme()
  // 收集当前显示的点位(同 collectPriceLines 的过滤逻辑)
  const visible: PriceLevel[] = []
  for (const group of LEVEL_GROUPS) {
    if (!activeTypes.has(group.key)) continue
    for (const point of levels[group.key] ?? []) {
      if (point.type === 'pivot' && point.rank !== undefined && point.rank > pivotRank) continue
      visible.push(point)
    }
  }
  if (visible.length === 0) return null

  // 按方向分两组:压力位(在当前价之上) / 支撑位(之下),各自按距当前价远近排序
  const cur = close ?? visible[0].value
  const resistances = visible
    .filter(point => point.side === 'resistance')
    .sort((a, b) => a.value - b.value)        // 由近及远(低→高)
  const supports = visible
    .filter(point => point.side === 'support')
    .sort((a, b) => b.value - a.value)         // 由近及远(高→低)
  const neutrals = visible.filter(point => point.side === 'neutral')

  const fmtPct = (value: number) => {
    if (!cur) return ''
    const pct = ((value - cur) / cur) * 100
    const sign = pct >= 0 ? '+' : ''
    return `${sign}${pct.toFixed(1)}%`
  }

  const Row = ({ point }: { point: PriceLevel }) => {
    const color = LEVEL_GROUPS.find(group => group.key === point.type)?.color ?? theme.text
    const key = levelKey(point.type, point.value)
    const hit = hoveredKey === key
    const dim = hoveredKey != null && !hit
    return (
      <div
        onMouseEnter={() => onHover(key)}
        onMouseLeave={() => onHover(null)}
        className={`flex items-center gap-2 py-0.5 px-1.5 -mx-1.5 rounded transition-colors cursor-default ${
          hit ? 'bg-elevated/60' : ''
        }`}
        style={dim ? { opacity: 0.35 } : undefined}
      >
        <span className="h-1.5 w-1.5 rounded-full shrink-0 transition-transform" style={{ backgroundColor: color, transform: hit ? 'scale(1.5)' : 'scale(1)' }} />
        <span className={`text-[11px] w-24 shrink-0 truncate ${hit ? 'text-foreground font-medium' : 'text-secondary'}`}>{point.label}</span>
        <span className={`text-[11px] font-mono ${hit ? 'text-foreground font-bold' : 'text-foreground'}`}>{point.value.toFixed(2)}</span>
        <span className="text-[9px] font-mono text-muted">{fmtPct(point.value)}</span>
      </div>
    )
  }

  return (
    <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 rounded-lg border border-border/40 bg-base/20 px-3 py-2">
      {/* 当前价 */}
      <div className="sm:col-span-2 flex items-center gap-2 pb-1 border-b border-border/30 mb-0.5">
        <span className="text-[10px] text-muted">当前价</span>
        <span className="text-xs font-mono font-medium text-foreground">{cur.toFixed(2)}</span>
      </div>
      {/* 压力位(从近到远,即从低到高)倒序展示:最高的在最上 */}
      {resistances.length > 0 && (
        <div>
          <div className="text-[10px] font-medium text-bear mb-0.5">压力位 ↑</div>
          {[...resistances].reverse().map((point, index) => <Row key={`r-${index}`} point={point} />)}
        </div>
      )}
      {/* 支撑位 + 中性(枢轴位 P) */}
      <div>
        {supports.length > 0 && (
          <>
            <div className="text-[10px] font-medium text-bull mb-0.5">支撑位 ↓</div>
            {supports.map((point, index) => <Row key={`s-${index}`} point={point} />)}
          </>
        )}
        {neutrals.length > 0 && (
          <div className={supports.length > 0 ? 'mt-2' : ''}>
            {supports.length === 0 && <div className="text-[10px] font-medium text-muted mb-0.5">枢轴位</div>}
            {neutrals.map((point, index) => <Row key={`n-${index}`} point={point} />)}
          </div>
        )}
      </div>
    </div>
  )
}
