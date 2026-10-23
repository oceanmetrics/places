// analytics wiring: the id rule of the build variable, and the build check (scripts/check-ga.mjs) on small dists
import { mkdirSync, mkdtempSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'
// a plain .mjs script, also run by pages.yml after the build
import { checkGa } from '../../scripts/check-ga.mjs'
import { gaId } from './ga'

describe('gaId: VITE_GA_ID, or "" (analytics off)', () => {
  it('unset or empty is off', () => {
    expect(gaId(undefined)).toBe('')
    expect(gaId('')).toBe('')
  })
  it('a GA4 id is kept, trimmed', () => expect(gaId(' G-TEST000000 ')).toBe('G-TEST000000'))
  it('anything else is off', () => {
    for (const bad of ['UA-1234-1', 'g-test000000', 'G-TEST000000"><script>', 'G-X&y=1']) expect(gaId(bad)).toBe('')
  })
})

const dist = (files: Record<string, string>) => {
  const d = mkdtempSync(join(tmpdir(), 'ga-dist-'))
  for (const [f, s] of Object.entries(files)) { mkdirSync(join(d, f, '..'), { recursive: true }); writeFileSync(join(d, f), s) }
  return d
}
const BAR = 'const s="https://www.googletagmanager.com/gtag/js?id=";'

describe('checkGa: the built output', () => {
  it('unset: a pass with no id and no script tag; a stray id or a script tag fails', () => {
    expect(checkGa(dist({ 'index.html': '<om-nav></om-nav>', 'assets/a.js': BAR }), '')).toEqual([])
    expect(checkGa(dist({ 'index.html': '', 'assets/a.js': 'x("G-TEST000000")' }), '')).toEqual(['a measurement id that was not given: G-TEST000000'])
    expect(checkGa(dist({ 'p/x/index.html': '<script async src="https://www.googletagmanager.com/gtag/js?id=G-TEST000000"></script>' }), 'G-TEST000000'))
      .toContain('p/x/index.html: a gtag.js script tag in the page')
  })
  it('set: a pass when the id and the bar\'s loader are in the bundle', () => {
    expect(checkGa(dist({ 'index.html': '', 'assets/a.js': `${BAR}x("G-TEST000000")` }), 'G-TEST000000')).toEqual([])
    expect(checkGa(dist({ 'index.html': '', 'assets/a.js': BAR }), 'G-TEST000000')).toEqual(['the given id G-TEST000000 is not in the build'])
    expect(checkGa(dist({ 'index.html': '', 'assets/a.js': 'x("G-TEST000000")' }), 'G-TEST000000'))
      .toEqual(['the bar in the build has no analytics loader (@oceanmetrics/nav >= 0.2.0)'])
  })
})
