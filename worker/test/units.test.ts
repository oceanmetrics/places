import { describe, expect, it } from 'vitest'
import { originAllowed } from '../src/cors'
import { classify, objectKey, target } from '../src/paths'
import { parseRange, preconditionStatus, resolveRange } from '../src/range'
import { evaluateCap, monthLabel } from '../src/meter'

describe('paths', () => {
  it('classifies by extension; only parquet/pmtiles outside index/ fall to the anonymous tier', () => {
    expect(classify('gazetteer/catalog.json')).toEqual({ cls: 'stac', gate: 'open' })
    expect(classify('gazetteer/a/b.parquet')).toEqual({ cls: 'parquet', gate: 'anonymous' })
    expect(classify('gazetteer/a/b.PMTILES')).toEqual({ cls: 'pmtiles', gate: 'anonymous' })
    expect(classify('gazetteer/index/crosswalk.parquet')).toEqual({ cls: 'parquet', gate: 'open' })
    expect(classify('gazetteer/README.md')).toEqual({ cls: 'other', gate: 'open' })
    expect(classify('gazetteer/a/b.thumb.jpg')).toEqual({ cls: 'other', gate: 'open' })
  })
  it('unlisted: class unlisted, every path needs a key except gazetteer/index/', () => {
    expect(classify('gazetteer/mr_eez/places.parquet', 'unlisted')).toEqual({ cls: 'unlisted', gate: 'key' })
    expect(classify('gazetteer/mr_eez/README.md', 'unlisted')).toEqual({ cls: 'unlisted', gate: 'key' })
    expect(classify('gazetteer/index/unlisted.json', 'unlisted')).toEqual({ cls: 'unlisted', gate: 'open' })
  })
  it('routes /unlisted/gazetteer/... to the unlisted bucket with the same key layout', () => {
    expect(target('/gazetteer/a/b.json')).toEqual({ store: 'public', key: 'gazetteer/a/b.json', prefix: 'gazetteer' })
    expect(target('/unlisted/gazetteer/mr_eez/places.parquet')).toEqual({ store: 'unlisted', key: 'gazetteer/mr_eez/places.parquet', prefix: 'unlisted' })
    expect(objectKey('/unlisted/gazetteer/mr_eez/places.parquet')).toBeNull()
    for (const p of ['/unlisted/', '/unlisted/x.json', '/unlisted/gazetteer/../x', '/unlisted/unlisted/gazetteer/a.json']) expect(target(p), p).toBeNull()
  })
  it('rejects paths outside the served prefixes and traversal', () => {
    expect(objectKey('/gazetteer/a/b.json')).toBe('gazetteer/a/b.json')
    expect(objectKey('/gazetteer/a%20b.json')).toBe('gazetteer/a b.json')
    for (const p of ['/x/y.json', '/gazetteer', '/gazetteer/../x', '/gazetteer//x', '/gazetteer/%E0%A4%A']) expect(objectKey(p), p).toBeNull()
  })
})

describe('range', () => {
  it('parses single ranges only', () => {
    expect(parseRange('bytes=0-99')).toEqual({ offset: 0, length: 100 })
    expect(parseRange('bytes=5-')).toEqual({ offset: 5 })
    expect(parseRange('bytes=-7')).toEqual({ suffix: 7 })
    for (const h of [null, '', 'bytes=-', 'bytes=9-1', 'bytes=0-1,3-4', 'items=0-1', 'bytes=-0']) expect(parseRange(h), String(h)).toBeNull()
  })
  it('resolves against a size, clamping the end', () => {
    expect(resolveRange({ offset: 0, length: 100 }, 50)).toEqual({ start: 0, end: 49 })
    expect(resolveRange({ suffix: 100 }, 50)).toEqual({ start: 0, end: 49 })
    expect(resolveRange({ offset: 50 }, 50)).toBe('unsatisfiable')
  })
  it('evaluates preconditions', () => {
    const h = (o: Record<string, string>) => new Headers(o)
    expect(preconditionStatus(h({}), '"a"')).toBeNull()
    expect(preconditionStatus(h({ 'if-none-match': 'W/"a", "b"' }), '"a"')).toBe(304)
    expect(preconditionStatus(h({ 'if-none-match': '*' }), '"a"')).toBe(304)
    expect(preconditionStatus(h({ 'if-match': '"b"' }), '"a"')).toBe(412)
    expect(preconditionStatus(h({ 'if-match': '"b", "a"' }), '"a"')).toBeNull()
  })
})

describe('origins and caps', () => {
  it('matches exact origins and wildcard patterns; empty list means any', () => {
    expect(originAllowed('https://a.org', undefined)).toBe(true)
    expect(originAllowed('https://a.org', [])).toBe(true)
    expect(originAllowed('https://a.org', ['https://a.org'])).toBe(true)
    expect(originAllowed('https://A.org', ['https://a.org'])).toBe(true)
    expect(originAllowed('https://b.a.org', ['https://*.a.org'])).toBe(true)
    expect(originAllowed('https://a.org', ['https://*.a.org'])).toBe(false)
    expect(originAllowed('https://xa.org.evil.com', ['https://*.a.org'])).toBe(false)
    expect(originAllowed('http://localhost:5173', ['http://localhost:*'])).toBe(true)
    expect(originAllowed('https://evil.com', ['https://a.org'])).toBe(false)
  })
  it('evaluates caps: ok / soft (default 80 %) / hard; no cap is always ok', () => {
    expect(evaluateCap(5, { app: 'x' }).state).toBe('ok')
    expect(evaluateCap(79, { app: 'x', monthly_cap_bytes: 100 }).state).toBe('ok')
    expect(evaluateCap(80, { app: 'x', monthly_cap_bytes: 100 })).toMatchObject({ state: 'soft', pct: 80 })
    expect(evaluateCap(100, { app: 'x', monthly_cap_bytes: 100 }).state).toBe('hard')
    expect(evaluateCap(60, { app: 'x', monthly_cap_bytes: 100, soft_pct: 0.5 }).state).toBe('soft')
    expect(monthLabel(new Date('2026-12-31T23:59:59Z'))).toBe('2026-12')
  })
})
