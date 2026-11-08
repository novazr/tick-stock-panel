// @vitest-environment jsdom
import { afterEach, describe, expect, it } from 'vitest'
import { applyMarket, marketPalette, paletteFor, restoreMarket } from './market-palette'

afterEach(() => {
  delete document.documentElement.dataset.market
  localStorage.clear()
})

describe('market palette', () => {
  it('A 股红涨绿跌', () => {
    const p = paletteFor('cn')
    expect(p.bull).toBe('#F04438')
    expect(p.bear).toBe('#12B76A')
    expect(p.bullAlpha(0.5)).toBe('rgba(240,68,56,0.5)')
  })

  it('美股绿涨红跌', () => {
    const p = paletteFor('us')
    expect(p.bull).toBe('#12B76A')
    expect(p.bear).toBe('#F04438')
    expect(p.bearMuted).toBe('#C74040')
  })

  it('未设置市场时默认 A 股', () => {
    expect(marketPalette().bull).toBe('#F04438')
  })

  it('applyMarket 写入 html 属性并缓存,restoreMarket 可恢复', () => {
    applyMarket('us')
    expect(document.documentElement.dataset.market).toBe('us')
    expect(marketPalette().bull).toBe('#12B76A')
    delete document.documentElement.dataset.market
    restoreMarket()
    expect(document.documentElement.dataset.market).toBe('us')
  })

  it('未知值按 A 股处理', () => {
    applyMarket(undefined)
    expect(document.documentElement.dataset.market).toBe('cn')
  })
})
