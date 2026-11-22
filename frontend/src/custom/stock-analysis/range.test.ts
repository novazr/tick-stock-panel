import { expect, it } from 'vitest'
import { ANALYSIS_RANGES, analysisDateRange } from './range'

it('keeps the one-year view on the rolling window request', () => {
  expect(analysisDateRange('1y', '2026-11-20')).toBeNull()
})

it('converts multi-year ranges to explicit start and end dates', () => {
  expect(analysisDateRange('3y', '2026-11-20')).toEqual({ start: '2023-11-20', end: '2026-11-20' })
  expect(analysisDateRange('5y', '2026-11-20')).toEqual({ start: '2021-11-20', end: '2026-11-20' })
  expect(analysisDateRange('10y', '2026-11-20')).toEqual({ start: '2016-11-20', end: '2026-11-20' })
})

it('falls back to Feb 28 when the start year has no leap day', () => {
  expect(analysisDateRange('3y', '2028-02-29')).toEqual({ start: '2025-02-28', end: '2028-02-29' })
})

it('requests everything available for the all range', () => {
  expect(analysisDateRange('all', '2026-11-20')).toEqual({ start: '1970-01-01', end: '2026-11-20' })
})

it('lists ranges from shortest to longest', () => {
  expect(ANALYSIS_RANGES.map(item => item.key)).toEqual(['1y', '3y', '5y', '10y', 'all'])
})
