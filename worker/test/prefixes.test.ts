// every published prefix of the bucket: table-driven by prefix and type ----
import { beforeAll, describe, expect, it } from 'vitest'
import { env } from 'cloudflare:test'
import { handle } from '../src/index'
import { classify, target, SERVED_MESSAGE, type Gate, type PathClass } from '../src/paths'
import { GOOD_KEY, ORIGIN, PARQUET, PMTILES, get, now, rig, seed } from './helpers'

const run = (r: ReturnType<typeof rig>, req: Request) => handle(req, r.env, now)
const TIF = new Uint8Array(20_000).map((_, i) => (i * 5 + 2) % 239)
const GAZ_LINK   = '<https://storage.oceanmetrics.io/gazetteer/credits>; rel="license"'
const ATLAS_LINK = '<https://storage.oceanmetrics.io/atlas/index/credits>; rel="license"'

async function seedPrefixes(): Promise<void> {
  const put = (k: string, v: Uint8Array | string, contentType?: string) =>
    env.BUCKET.put(k, v, contentType ? { httpMetadata: { contentType } } : undefined)
  await put('indicators/indicators.json', JSON.stringify({ indicators: [] }))
  await put('indicators/coverage.parquet', PARQUET)
  await put('indicators/values/indicator=sst/coll=mpa/data.parquet', PARQUET)
  await put('indicators/README.md', '# indicators')
  await put('indicators/producers/sst.svg', '<svg/>')
  await put('indicators/feeds/all.xml', '<feed xmlns="http://www.w3.org/2005/Atom"/>', 'application/atom+xml; charset=utf-8')
  await put('indicators/feeds/place=NMS:CINMS.xml', '<feed xmlns="http://www.w3.org/2005/Atom"/>')   // no stored type
  await put('indicators/feeds/all.atom', '<feed xmlns="http://www.w3.org/2005/Atom"/>', 'application/octet-stream')
  await put('indicators/feeds/all.xml.gz', PARQUET)
  await put('atlas/catalog.json', JSON.stringify({ type: 'Catalog' }))
  await put('atlas/index/credits', 'atlas credits')
  await put('atlas/aquamaps_eov/collection.json', JSON.stringify({ type: 'Collection' }))
  await put('atlas/aquamaps_eov/score_risk_3857.tif', TIF)
  await put('atlas/aquamaps_eov/thumbnail.png', 'png')
  await put('atlas/aquamaps_eov/eov_summary.csv', 'a,b\n1,2\n')
  await put('atlas/aquamaps_eov/h3_r5.parquet', PARQUET)
  await put('obis-h3/latest.json', JSON.stringify({ version: 'v20261001' }))
  await put('obis-h3/v20261001/h3_r3/part-0.parquet', PARQUET)
  await put('basemap/gebco/far.pmtiles', PMTILES)
  await put('basemap/osm/land.pmtiles', PMTILES, 'application/octet-stream')   // rclone's generic type
  await put('marine-atlas/index.html', '<html>marine atlas</html>', 'text/html')
  await put('marine-atlas/versions.json', JSON.stringify([]))
  await put('marine-atlas/latest.txt', 'v3')
  await put('marine-atlas/cog/index.html', '<html>cog</html>')
  await put('marine-atlas/v3/sdm.duckdb', PARQUET)
  await put('marine-atlas/v3/layers.fgb', PARQUET)
  await put('marine-atlas/v3/bundle.zip', PARQUET)
  await put('marine-atlas/v3/cell.tif', TIF)
  await put('issues/apps-8/walrus.jpg', 'jpg')
  await put('atlas-restricted/coll/collection.json', JSON.stringify({ type: 'Collection' }))
  await put('atlas-restricted/coll/data.parquet', PARQUET)
  await put('backups/db.dump', 'SECRET')
  await put('backups/index.html', '<html>backups</html>')
  await put('index.html', '<html>root</html>')
  await put('README.md', '# root')
  await put('nc.parquet', PARQUET)
  await put('indicators.pmtiles', PMTILES)
}

beforeAll(async () => { await seed(); await seedPrefixes() })

describe('target(): the allow-list', () => {
  const cases: [string, { store: 'public' | 'unlisted', key: string, prefix: string } | null][] = [
    ['/gazetteer/catalog.json',                    { store: 'public', key: 'gazetteer/catalog.json', prefix: 'gazetteer' }],
    ['/indicators/coverage.parquet',               { store: 'public', key: 'indicators/coverage.parquet', prefix: 'indicators' }],
    ['/atlas/aquamaps_eov/collection.json',        { store: 'public', key: 'atlas/aquamaps_eov/collection.json', prefix: 'atlas' }],
    ['/obis-h3/latest.json',                       { store: 'public', key: 'obis-h3/latest.json', prefix: 'obis-h3' }],
    ['/basemap/gebco/far.pmtiles',                 { store: 'public', key: 'basemap/gebco/far.pmtiles', prefix: 'basemap' }],
    ['/marine-atlas/versions.json',                { store: 'public', key: 'marine-atlas/versions.json', prefix: 'marine-atlas' }],
    ['/issues/apps-8/walrus.jpg',                  { store: 'public', key: 'issues/apps-8/walrus.jpg', prefix: 'issues' }],
    ['/atlas-restricted/coll/data.parquet',        { store: 'public', key: 'atlas-restricted/coll/data.parquet', prefix: 'atlas-restricted' }],
    ['/unlisted/gazetteer/mr_eez/places.parquet',  { store: 'unlisted', key: 'gazetteer/mr_eez/places.parquet', prefix: 'unlisted' }],
    // folder urls read index.html under them
    ['/marine-atlas/',                             { store: 'public', key: 'marine-atlas/index.html', prefix: 'marine-atlas' }],
    ['/marine-atlas/cog/',                         { store: 'public', key: 'marine-atlas/cog/index.html', prefix: 'marine-atlas' }],
    ['/gazetteer/',                                { store: 'public', key: 'gazetteer/index.html', prefix: 'gazetteer' }],
    ['/',                                          { store: 'public', key: 'index.html', prefix: 'root' }],
    // root files
    ['/index.html',                                { store: 'public', key: 'index.html', prefix: 'root' }],
    ['/README.md',                                 { store: 'public', key: 'README.md', prefix: 'root' }],
    // everything else
    ['/backups/',                                  null],
    ['/backups/db.dump',                           null],
    ['/backups/index.html',                        null],
    ['/BACKUPS/db.dump',                           null],
    ['/%62ackups/db.dump',                         null],
    ['/gazetteer/../backups/db.dump',              null],
    ['/nc.parquet',                                null],
    ['/indicators.pmtiles',                        null],
    ['/readme.md',                                 null],
    ['/marine-atlas',                              null],
    ['/unlisted/atlas/x.json',                     null],
    ['/unlisted/backups/db.dump',                  null],
    ['/atlas//x.json',                             null],
  ]
  for (const [path, want] of cases) it(`${path} -> ${want ? want.key : '404'}`, () => expect(target(path)).toEqual(want))
})

describe('classify(): by type, not by prefix', () => {
  const cases: [string, PathClass, Gate][] = [
    // keyless metadata everywhere public
    ['indicators/indicators.json',                 'stac',     'open'],
    ['atlas/aquamaps_eov/collection.json',         'stac',     'open'],
    ['obis-h3/latest.json',                        'stac',     'open'],
    ['marine-atlas/index.html',                    'other',    'open'],
    ['marine-atlas/latest.txt',                    'other',    'open'],
    ['indicators/README.md',                       'other',    'open'],
    ['atlas/aquamaps_eov/thumbnail.png',           'other',    'open'],
    ['issues/apps-8/walrus.jpg',                   'other',    'open'],
    ['issues/apps-8/walrus.JPEG',                  'other',    'open'],
    ['atlas/aquamaps_eov/eov_summary.csv',         'other',    'open'],
    ['indicators/producers/sst.svg',               'other',    'open'],
    ['indicators/feeds/all.xml',                   'other',    'open'],
    ['indicators/feeds/place=NMS:CINMS.XML',       'other',    'open'],
    ['indicators/feeds/all.atom',                  'other',    'open'],
    // seeded fault: a compressed feed is data, not a feed
    ['indicators/feeds/all.xml.gz',                'data',     'anonymous'],
    ['gazetteer/credits',                          'other',    'open'],
    ['README.md',                                  'other',    'open'],
    // data: key tiers, anonymous limiter without a key
    ['indicators/coverage.parquet',                'parquet',  'anonymous'],
    ['obis-h3/v20261001/h3_r3/part-0.parquet',     'parquet',  'anonymous'],
    ['basemap/gebco/far.pmtiles',                  'pmtiles',  'anonymous'],
    ['atlas/aquamaps_eov/score_risk_3857.tif',     'tif',      'anonymous'],
    ['gazetteer/fknms/rasters/a.TIFF',             'tif',      'anonymous'],
    ['marine-atlas/v3/sdm.duckdb',                 'data',     'anonymous'],
    ['marine-atlas/v3/bundle.zip',                 'data',     'anonymous'],
    ['marine-atlas/v3/table.csv.gz',               'data',     'anonymous'],
    ['marine-atlas/v3/layers.fgb',                 'data',     'anonymous'],
    ['marine-atlas/v3/unknown.nc',                 'data',     'anonymous'],
    ['gazetteer/.gitignore',                       'data',     'anonymous'],
    // the gazetteer index stays open whatever the type
    ['gazetteer/index/crosswalk.parquet',          'parquet',  'open'],
    // restricted: every file needs a key, class unlisted
    ['atlas-restricted/coll/collection.json',      'unlisted', 'key'],
    ['atlas-restricted/coll/data.parquet',         'unlisted', 'key'],
    ['atlas-restricted/coll/thumbnail.png',        'unlisted', 'key'],
  ]
  for (const [key, cls, gate] of cases) it(`${key} -> ${cls}/${gate}`, () => expect(classify(key)).toEqual({ cls, gate }))
})

describe('every published prefix through handle()', () => {
  interface Case {
    path: string, key?: boolean, range?: string, origin?: string,
    status: number, cls?: string, tier?: string, prefix: string, type?: string, link?: string | null, error?: string,
  }
  const cases: Case[] = [
    // keyless metadata: open tier, no limiter, a bad key would be ignored
    { path: '/indicators/indicators.json',            status: 200, cls: 'stac',  tier: 'open', prefix: 'indicators', type: 'application/json', link: null },
    { path: '/atlas/aquamaps_eov/collection.json',    status: 200, cls: 'stac',  tier: 'open', prefix: 'atlas', type: 'application/json', link: ATLAS_LINK },
    { path: '/obis-h3/latest.json',                   status: 200, cls: 'stac',  tier: 'open', prefix: 'obis-h3', link: null },
    { path: '/marine-atlas/versions.json',            status: 200, cls: 'stac',  tier: 'open', prefix: 'marine-atlas' },
    { path: '/atlas/aquamaps_eov/thumbnail.png',      status: 200, cls: 'other', tier: 'open', prefix: 'atlas', type: 'image/png' },
    { path: '/atlas/aquamaps_eov/eov_summary.csv',    status: 200, cls: 'other', tier: 'open', prefix: 'atlas', type: 'text/csv; charset=utf-8' },
    { path: '/indicators/README.md',                  status: 200, cls: 'other', tier: 'open', prefix: 'indicators' },
    { path: '/indicators/producers/sst.svg',          status: 200, cls: 'other', tier: 'open', prefix: 'indicators', type: 'image/svg+xml' },
    // the Atom feeds: keyless, never the anonymous limiter; the stored type wins, else the extension's
    { path: '/indicators/feeds/all.xml',              status: 200, cls: 'other', tier: 'open', prefix: 'indicators', type: 'application/atom+xml; charset=utf-8' },
    { path: '/indicators/feeds/place=NMS:CINMS.xml',  status: 200, cls: 'other', tier: 'open', prefix: 'indicators', type: 'application/xml; charset=utf-8' },
    { path: '/indicators/feeds/all.atom',             status: 200, cls: 'other', tier: 'open', prefix: 'indicators', type: 'application/atom+xml; charset=utf-8' },
    { path: '/indicators/feeds/all.xml.gz',           range: 'bytes=0-99', status: 206, cls: 'data', tier: 'anonymous', prefix: 'indicators', type: 'application/gzip' },
    { path: '/issues/apps-8/walrus.jpg',              status: 200, cls: 'other', tier: 'open', prefix: 'issues', type: 'image/jpeg' },
    // public data keyless: anonymous tier through the limiter
    { path: '/indicators/coverage.parquet',           range: 'bytes=0-99', status: 206, cls: 'parquet', tier: 'anonymous', prefix: 'indicators', type: 'application/vnd.apache.parquet', link: null },
    { path: '/indicators/values/indicator=sst/coll=mpa/data.parquet', range: 'bytes=0-99', status: 206, cls: 'parquet', tier: 'anonymous', prefix: 'indicators' },
    { path: '/obis-h3/v20261001/h3_r3/part-0.parquet', range: 'bytes=0-99', status: 206, cls: 'parquet', tier: 'anonymous', prefix: 'obis-h3' },
    { path: '/basemap/gebco/far.pmtiles',             range: 'bytes=0-16383', status: 206, cls: 'pmtiles', tier: 'anonymous', prefix: 'basemap', type: 'application/vnd.pmtiles' },
    { path: '/basemap/osm/land.pmtiles',              range: 'bytes=0-99', status: 206, cls: 'pmtiles', tier: 'anonymous', prefix: 'basemap', type: 'application/vnd.pmtiles' },
    { path: '/atlas/aquamaps_eov/score_risk_3857.tif', range: 'bytes=0-99', status: 206, cls: 'tif', tier: 'anonymous', prefix: 'atlas', type: 'image/tiff', link: ATLAS_LINK },
    { path: '/marine-atlas/v3/sdm.duckdb',            range: 'bytes=0-99', status: 206, cls: 'data', tier: 'anonymous', prefix: 'marine-atlas' },
    { path: '/marine-atlas/v3/layers.fgb',            range: 'bytes=0-99', status: 206, cls: 'data', tier: 'anonymous', prefix: 'marine-atlas' },
    { path: '/marine-atlas/v3/bundle.zip',            range: 'bytes=0-99', status: 206, cls: 'data', tier: 'anonymous', prefix: 'marine-atlas', type: 'application/zip' },
    // public data keyed: the key tier
    { path: '/indicators/coverage.parquet',           key: true, range: 'bytes=0-99', origin: ORIGIN, status: 206, cls: 'parquet', tier: 'free', prefix: 'indicators' },
    { path: '/atlas/aquamaps_eov/score_risk_3857.tif', key: true, range: 'bytes=0-99', status: 206, cls: 'tif', tier: 'free', prefix: 'atlas' },
    { path: '/basemap/gebco/far.pmtiles',             key: true, range: 'bytes=0-16383', status: 206, cls: 'pmtiles', tier: 'free', prefix: 'basemap' },
    { path: '/marine-atlas/v3/cell.tif',              key: true, range: 'bytes=0-99', status: 206, cls: 'tif', tier: 'free', prefix: 'marine-atlas', link: null },
    // restricted: key required, no anonymous tier
    { path: '/atlas-restricted/coll/data.parquet',    range: 'bytes=0-99', status: 403, cls: 'unlisted', tier: 'open', prefix: 'atlas-restricted', error: 'key_required' },
    { path: '/atlas-restricted/coll/collection.json', status: 403, cls: 'unlisted', prefix: 'atlas-restricted', error: 'key_required' },
    { path: '/atlas-restricted/x',                    status: 403, cls: 'unlisted', prefix: 'atlas-restricted', error: 'key_required' },
    { path: '/atlas-restricted/coll/data.parquet',    key: true, range: 'bytes=0-99', status: 206, cls: 'unlisted', tier: 'free', prefix: 'atlas-restricted', link: null },
    { path: '/atlas-restricted/coll/collection.json', key: true, status: 200, cls: 'unlisted', tier: 'free', prefix: 'atlas-restricted' },
    // backups and other unserved paths: 404 with the served-prefixes message, key or not
    { path: '/backups/',                              status: 404, prefix: 'backups', error: 'not_found' },
    { path: '/backups/db.dump',                       status: 404, prefix: 'backups', error: 'not_found' },
    { path: '/backups/db.dump',                       key: true, status: 404, prefix: 'backups', error: 'not_found' },
    { path: '/backups/index.html',                    status: 404, prefix: 'backups', error: 'not_found' },
    { path: '/nc.parquet',                            status: 404, prefix: 'nc.parquet', error: 'not_found' },
    { path: '/indicators.pmtiles',                    status: 404, prefix: 'indicators.pmtiles', error: 'not_found' },
    // root files and folder index rewrite
    { path: '/index.html',                            status: 200, cls: 'other', tier: 'open', prefix: 'root', type: 'text/html; charset=utf-8', link: null },
    { path: '/',                                      status: 200, cls: 'other', tier: 'open', prefix: 'root' },
    { path: '/README.md',                             status: 200, cls: 'other', tier: 'open', prefix: 'root', type: 'text/markdown; charset=utf-8' },
    { path: '/marine-atlas/',                         status: 200, cls: 'other', tier: 'open', prefix: 'marine-atlas', type: 'text/html' },
    { path: '/marine-atlas/cog/',                     status: 200, cls: 'other', tier: 'open', prefix: 'marine-atlas' },
    { path: '/indicators/',                           status: 404, cls: 'other', tier: 'open', prefix: 'indicators', error: 'not_found' },
    // gazetteer unchanged: Link on its data
    { path: '/gazetteer/mpa/places.parquet',          range: 'bytes=0-99', status: 206, cls: 'parquet', tier: 'anonymous', prefix: 'gazetteer', link: GAZ_LINK },
  ]
  for (const c of cases) {
    it(`${c.key ? 'keyed' : 'keyless'} ${c.path} -> ${c.status}${c.error ? ` ${c.error}` : ''}`, async () => {
      const r = rig()
      const headers: Record<string, string> = { 'cf-connecting-ip': '203.0.113.7' }
      if (c.range) headers.range = c.range
      if (c.origin) headers.origin = c.origin
      const res = await run(r, get(`${c.path}${c.key ? `?key=${GOOD_KEY}` : ''}`, { headers }))
      expect(res.status).toBe(c.status)
      expect(res.headers.get('access-control-allow-origin')).toBe(c.origin && c.key ? c.origin : '*')
      if (c.type)  expect(res.headers.get('content-type')).toBe(c.type)
      if (c.link !== undefined) expect(res.headers.get('link')).toBe(c.link)
      if (c.status === 206) expect(res.headers.get('content-range')).toMatch(/^bytes \d+-\d+\/\d+$/)
      if (c.error) {
        const body = await res.json() as { error: string, message?: string }
        expect(body.error).toBe(c.error)
        if (c.status === 404 && !c.cls) expect(body.message).toBe(SERVED_MESSAGE)
      } else await res.arrayBuffer()
      // the anonymous limiter runs only for keyless data
      expect(r.limited.anon).toEqual(c.tier === 'anonymous' ? ['203.0.113.7'] : [])
      expect(r.points).toHaveLength(1)
      const b = r.points[0].blobs
      if (c.cls)  expect(b[2]).toBe(c.cls)
      if (c.tier) expect(b[4]).toBe(c.tier)
      expect(b[7]).toBe(c.prefix)
      expect(r.points[0].doubles[1]).toBe(c.status)
    })
  }

  it('regression: no request path reaches a backups/ object, however it is spelled', async () => {
    const r = rig()
    for (const p of ['/backups/db.dump', '/backups//db.dump', '/./backups/db.dump', '/gazetteer/../backups/db.dump',
      '/gazetteer/%2E%2E/backups/db.dump', '/%62ackups/db.dump', '/unlisted/../backups/db.dump', '/backups/', '/backups']) {
      const res = await run(r, get(`${p}?key=${GOOD_KEY}`))
      expect(res.status, p).toBe(404)
      expect(await res.text(), p).not.toContain('SECRET')
    }
  })

  it('un-ranged GET of a big non-gazetteer parquet: 200, class fullfile, warning header', async () => {
    const r = rig({ FULLFILE_BYTES: '10000' })
    const res = await run(r, get('/indicators/coverage.parquet'))
    expect(res.status).toBe(200)
    expect(res.headers.get('x-om-warn')).toContain('full-file-read')
    await res.arrayBuffer()
    expect(r.points[0].blobs[2]).toBe('fullfile')
  })

  it('keyed restricted data: wrong key is 403 invalid_key, wrong origin 403 origin_not_allowed', async () => {
    const r = rig()
    const bad = await run(r, get('/atlas-restricted/coll/data.parquet?key=WRONGKEY123456', { headers: { range: 'bytes=0-9' } }))
    expect(bad.status).toBe(403)
    expect((await bad.json() as { error: string }).error).toBe('invalid_key')
    const wo = await run(r, get(`/atlas-restricted/coll/data.parquet?key=${GOOD_KEY}`, { headers: { range: 'bytes=0-9', origin: 'https://evil.example.com' } }))
    expect(wo.status).toBe(403)
    expect((await wo.json() as { error: string }).error).toBe('origin_not_allowed')
  })
})
