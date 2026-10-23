// the basemap of the site's maps: CARTO's positron or dark-matter style composed by `@oceanmetrics/map` `composeStyle`
// with the GEBCO 2025 sea floor (colour relief and hillshade), the isobaths, the OSM land mask and the GEBCO undersea
// names, in both themes. the rules here are plain functions (tested): where the tiers are read from, where the place
// layers go in the stack, and the credit line. the map component (PlacesMap.svelte) only calls them.
import { BASEMAP_URL, DEFAULT_TILES, LAND_LAYER, baseStyle, composeStyle } from '@oceanmetrics/map'
import type { BasemapTiles, Theme } from '@oceanmetrics/map'
import type { StyleSpecification } from 'maplibre-gl'
import { store } from '../storage'

/**
 * where the GEBCO and OSM tiers are read from. the package's DEFAULT_TILES name storage.oceanmetrics.io/basemap/, which
 * answers 404 until the DNS cutover (`basemap` joins the storage host's allow-list: platform packages/map README,
 * "Open"); the same objects answer range reads at the bucket's path-style url. set this to BASEMAP_URL after the cutover.
 */
export const BASEMAP_BUCKET = store('basemap/')

/** every tier url under `from` moved under `to` (the regional list too); a null tier stays null */
export function tilesAt(tiles: Readonly<BasemapTiles> = DEFAULT_TILES, from: string = BASEMAP_URL, to: string = BASEMAP_BUCKET): BasemapTiles {
  const move = (u: string) => (u.startsWith(from) ? to + u.slice(from.length) : u)
  const opt = (u: string | null) => (u == null ? null : move(u))
  return {
    core: move(tiles.core), far: move(tiles.far), regional: tiles.regional?.map(move),
    contours: opt(tiles.contours), names: opt(tiles.names), land: opt(tiles.land),
  }
}

export const TILES = tilesAt()

export const themeOf = (dark: boolean): Theme => (dark ? 'dark' : 'light')

const SEA_FLOOR = /^gebco(-far|-regional(-\d+)?)?-(relief|shade)$|^gebco-contour/

/**
 * the layer the gazetteer's place layers go under: the first text layer above the land mask (the undersea names once the
 * tiers are on, else CARTO's first label), so the places draw over the sea floor, the isobaths and the land, and the names
 * stay readable on top; null (on top of everything) when the style has no text
 */
export function placesBeforeId(layers: readonly { id: string; type: string }[]): string | null {
  let from = 0
  layers.forEach((l, i) => { if (l.id === LAND_LAYER || l.id === 'water-inland' || SEA_FLOOR.test(l.id)) from = i + 1 })
  return layers.slice(from).find((l) => l.type === 'symbol')?.id ?? null
}

/** a style's own attribution, every source's once, as html (CARTO's carries its links); the GEBCO and OSM lines with the tiers */
export function styleCredit(style: { sources?: Record<string, unknown> } | null | undefined): string {
  const seen = new Set<string>()
  for (const src of Object.values(style?.sources ?? {})) {
    const a = (src as { attribution?: unknown })?.attribution
    if (typeof a === 'string' && a.trim()) seen.add(a.trim())
  }
  return [...seen].join(' · ')
}

/** what the map boots on before the style arrives: a plain sea, so a CARTO outage still leaves a map */
export const PLAIN_SEA = (dark: boolean): StyleSpecification => ({
  version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': dark ? '#0e1a24' : '#d4e4ec' } }],
})

/**
 * the style of a theme: CARTO's own (`dem: false`, the boot style: MapLibre schedules no frame while a source fails, so the
 * first paint never waits on the terrain tiers) or composed with the tiers; a plain sea when CARTO does not answer
 */
export async function styleFor(dark: boolean, dem: boolean): Promise<StyleSpecification> {
  const theme = themeOf(dark)
  let base: StyleSpecification
  try { base = await baseStyle(theme) } catch { return PLAIN_SEA(dark) }
  return composeStyle(base, { theme, dem, tiles: TILES })
}
