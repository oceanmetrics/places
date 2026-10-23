// the Species section's "Species on the map" link: from a gazetteer place to the atlas OBIS layer (obis_h3) with the
// place selected and the camera on its box. the rule is written and tested in oceanmetrics/atlas
// (`src/lib/state/obisPlace.ts` `placeObisUrl`, `tests/obis/placeLink.test.ts`, `docs/obis-layer.md`); this is its port,
// with the same cases in obisLink.test.ts. the place token is layers.ts `placeToken` (the same `p.<id>.<name>` the atlas
// codec writes).
//
//   placeObisUrl({ placeId: 'NMS:CINMS', name: 'Channel Islands', bbox: [-120.65, 33.2, -118.85, 34.25] })
//   https://oceanmetrics.io/atlas/?c=obis_h3&i=all&dim.indicator=es&dim.period=all&res=auto&map=-119.75,33.725,8.38&collection=…#pl=p.NMS%253ACINMS.Channel%2520Islands
//
// - the query is the OBIS layer's grammar: `c=obis_h3`, `i=all` (or an EOV item), `dim.indicator` (default es),
//   `dim.period` (default all), `res=auto`;
// - `map=lon,lat,zoom` frames the place's box `[west, south, east, north]` (east may be past 180 or below west across the
//   antimeridian): the centre, and the zoom at which the larger side fills about two thirds of a 1280 px map, clamped to
//   1..10 (no box: no `map`);
// - the hash `pl` is the place token, written the way the atlas writes a hash value (URLSearchParams, then `,`, `:` and
//   `/` unescaped), so its `%` is `%25`.
import { ATLAS_APP, placeToken } from './layers'

/** the OBIS H3 collection in the bucket. drop when `atlas/catalog.json` lists obis_h3 */
export const OBIS_COLLECTION_HREF = 'https://s3.us-east-1.amazonaws.com/oceanmetrics.io-public/obis-h3/collection.json'

export interface PlaceObisLink {
  /** the gazetteer place_id (`NMS:CINMS`, `MRGID:8432`) */
  placeId: string
  /** the display name carried in the token (shortened past 60 encoded characters) */
  name?: string
  /** [west, south, east, north] in degrees; absent, the link carries no camera */
  bbox?: readonly number[] | null
  /** `all` (default) or an EOV item id */
  item?: string
  indicator?: 'es' | 'sp' | 'shannon' | 'simpson' | 'n'
  /** `all` (default), a decade `1990s` or a year `2015` */
  period?: string
  /** the atlas app url; default https://oceanmetrics.io/atlas/ */
  app?: string
  /** the collection.json the atlas loads obis_h3 from; default OBIS_COLLECTION_HREF, '' for none (once the catalog lists it) */
  collection?: string
}

const round = (v: number, d: number) => Number(v.toFixed(d))
const pretty = (p: URLSearchParams) => p.toString().replace(/%2C/g, ',').replace(/%3A/g, ':').replace(/%2F/g, '/')

/** the camera that frames a box: centre and zoom (see the header), or null for a malformed box */
export function cameraForBbox(bbox: readonly number[] | null | undefined): { lon: number; lat: number; zoom: number } | null {
  if (!bbox || bbox.length !== 4 || !bbox.every(Number.isFinite)) return null
  const [w, s, e0, n] = bbox
  if (s > n || s < -90 || n > 90) return null
  const e = e0 < w ? e0 + 360 : e0 // across the antimeridian
  const dLon = Math.max(e - w, 1e-6)
  const dLat = Math.max(n - s, 1e-6)
  let lon = (w + e) / 2
  if (lon > 180) lon -= 360
  const lat = (s + n) / 2
  // a 1280 px map at zoom z spans 1280/512 * 360 / 2^z degrees of longitude (512 px tiles); the side fills 2/3
  const span = Math.max(dLon, dLat / Math.max(Math.cos((lat * Math.PI) / 180), 0.2))
  const zoom = Math.log2((2.5 * 360 * (2 / 3)) / span)
  return { lon: round(lon, 3), lat: round(lat, 3), zoom: round(Math.min(10, Math.max(1, zoom)), 2) }
}

/** the atlas url of the OBIS layer with a gazetteer place selected */
export function placeObisUrl(link: PlaceObisLink): string {
  const app = (link.app ?? ATLAS_APP).replace(/\/*$/, '/')
  const q = new URLSearchParams()
  q.set('c', 'obis_h3')
  q.set('i', link.item ?? 'all')
  q.set('dim.indicator', link.indicator ?? 'es')
  q.set('dim.period', link.period ?? 'all')
  q.set('res', 'auto')
  const cam = cameraForBbox(link.bbox)
  if (cam) q.set('map', `${cam.lon},${cam.lat},${cam.zoom}`)
  const collection = link.collection ?? OBIS_COLLECTION_HREF
  if (collection) q.set('collection', collection)
  const tok = placeToken(link.placeId, link.name ?? '')
  return `${app}?${pretty(q)}${tok ? '#' + pretty(new URLSearchParams({ pl: tok })) : ''}`
}
