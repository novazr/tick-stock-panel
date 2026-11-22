/**
 * 个股分析页日 K 的时间范围档位。
 *
 * 「1年」是最近 365 个自然日的滚动窗口 (由后端按 days 计算, 不带日期边界),
 * 其余档位换算成明确的起止日期请求; 本地数据不足时后端只返回已有的部分。
 */

export type AnalysisRangeKey = '1y' | '3y' | '5y' | '10y' | 'all'

export const ANALYSIS_RANGES: { key: AnalysisRangeKey; label: string; years: number | null }[] = [
  { key: '1y', label: '1年', years: 1 },
  { key: '3y', label: '3年', years: 3 },
  { key: '5y', label: '5年', years: 5 },
  { key: '10y', label: '10年', years: 10 },
  { key: 'all', label: '全部', years: null },
]

/** 「全部」档位的起始日: 早于任何可同步到的日 K。 */
const ALL_START = '1970-01-01'

/**
 * 档位 → 起止日期; 「1年」返回 null, 表示沿用滚动窗口请求。
 * today 为 YYYY-MM-DD; 起始日取 N 年前的同月同日 (2 月 29 日回落到 28 日)。
 */
export function analysisDateRange(key: AnalysisRangeKey, today: string): { start: string; end: string } | null {
  if (key === '1y') return null
  if (key === 'all') return { start: ALL_START, end: today }
  const years = ANALYSIS_RANGES.find(item => item.key === key)?.years ?? 1
  const [year, month, day] = today.split('-').map(Number)
  const lastDay = new Date(Date.UTC(year - years, month, 0)).getUTCDate()
  const pad = (value: number) => String(value).padStart(2, '0')
  return { start: `${year - years}-${pad(month)}-${pad(Math.min(day, lastDay))}`, end: today }
}
