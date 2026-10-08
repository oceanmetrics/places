import type { StyleSpecification } from 'maplibre-gl'

// Esri raster basemaps, as in erddap-places: keyless. ArcGIS REST tile urls are {z}/{y}/{x} (row before column).
const ARC = 'https://services.arcgisonline.com/ArcGIS/rest/services/'
const src = (path: string, maxzoom: number) => ({ type: 'raster' as const, tiles: [`${ARC}${path}/MapServer/tile/{z}/{y}/{x}`], tileSize: 256, maxzoom })

export const BASEMAP_CREDIT = 'Basemap &copy; Esri, GEBCO, NOAA, National Geographic, Garmin, HERE and others'

/** the id gazetteer layers are inserted below, so place labels stay readable on top. */
export const LABELS_BELOW = 'labels-light'

/** light (ocean) + dark (dark gray canvas) basemaps with reference labels above; the theme only flips visibility. */
export const style: StyleSpecification = {
  version: 8,
  sources: {
    'base-light'  : src('Ocean/World_Ocean_Base', 13),
    'base-dark'   : src('Canvas/World_Dark_Gray_Base', 16),
    'labels-light': src('Ocean/World_Ocean_Reference', 13),
    'labels-dark' : src('Canvas/World_Dark_Gray_Reference', 16),
  },
  layers: [
    { id: 'base-light',   type: 'raster', source: 'base-light' },
    { id: 'base-dark',    type: 'raster', source: 'base-dark',   layout: { visibility: 'none' } },
    { id: 'labels-light', type: 'raster', source: 'labels-light' },
    { id: 'labels-dark',  type: 'raster', source: 'labels-dark', layout: { visibility: 'none' } },
  ],
}

/** show the basemap for the theme. */
export function applyTheme(map: { setLayoutProperty(id: string, k: string, v: string): unknown }, dark: boolean) {
  for (const id of ['base-light', 'labels-light']) map.setLayoutProperty(id, 'visibility', dark ? 'none' : 'visible')
  for (const id of ['base-dark', 'labels-dark']) map.setLayoutProperty(id, 'visibility', dark ? 'visible' : 'none')
}
