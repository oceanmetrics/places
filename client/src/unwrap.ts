import type { Geometry, Position } from 'geojson'

const EDGE = 1e-6

function* positions(g: Geometry): Generator<Position[]> {
  switch (g.type) {
    case 'Point': yield [g.coordinates]; break
    case 'MultiPoint': case 'LineString': yield g.coordinates; break
    case 'MultiLineString': case 'Polygon': yield* g.coordinates; break
    case 'MultiPolygon': for (const p of g.coordinates) yield* p; break
    case 'GeometryCollection': for (const x of g.geometries) yield* positions(x); break
  }
}

const shift = (c: any, dx: number): any => (typeof c[0] === 'number' ? [c[0] + dx, c[1], ...c.slice(2)] : c.map((x: any) => shift(x, dx)))

/**
 * Unwrap a geometry stored split at the antimeridian into contiguous longitudes beyond 180.
 *
 * The gazetteer cuts places that cross +/-180 into parts on each side. A geometry is treated as crossing when
 * one part touches +180 and another touches -180. Every part that lies in the western hemisphere (longitude
 * centre < 0) is then shifted by +360, so the parts abut at x = 180 and the place spans e.g. 170 to 196 instead
 * of jumping between 170 and -164. The parts stay separate polygons that share the x = 180 edge (they are not
 * dissolved), which fills, bounds and area calculations treat as one place. Geometries that do not cross are
 * returned unchanged (the same object). Wrap back with `wrapLongitude`.
 */
export function unwrapAntimeridian<G extends Geometry>(g: G): G {
  if (g.type !== 'MultiPolygon' && g.type !== 'MultiLineString' && g.type !== 'MultiPoint') return g
  const parts = g.coordinates as any[]
  const lons = (part: any): number[] => {
    const out: number[] = []
    const walk = (c: any) => (typeof c[0] === 'number' ? out.push(c[0]) : c.forEach(walk))
    walk(part)
    return out
  }
  let east = false, west = false
  for (const p of parts) for (const x of lons(p)) { if (x >= 180 - EDGE) east = true; if (x <= -180 + EDGE) west = true }
  if (!(east && west)) return g
  const moved = parts.map((p) => {
    const xs = lons(p)
    return (Math.min(...xs) + Math.max(...xs)) / 2 < 0 ? shift(p, 360) : p
  })
  return { ...g, coordinates: moved } as G
}

/** wrap a longitude back into [-180, 180]. */
export const wrapLongitude = (x: number): number => (x > 180 ? x - 360 : x < -180 ? x + 360 : x)

/** [west, south, east, north] of a geometry's coordinates. */
export function geometryBBox(g: Geometry): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity
  for (const line of positions(g)) for (const [x, y] of line) {
    if (x < x0) x0 = x; if (x > x1) x1 = x
    if (y < y0) y0 = y; if (y > y1) y1 = y
  }
  return [x0, y0, x1, y1]
}
