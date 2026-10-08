import type { Geometry, Position } from 'geojson'

/** decode ISO / OGC well-known binary (2D; Z and M ordinates are read and dropped) to GeoJSON. */
export function wkbToGeometry(buf: Uint8Array): Geometry {
  const v = new DataView(buf.buffer, buf.byteOffset, buf.byteLength)
  let o = 0
  const read = (): Geometry => {
    const le = v.getUint8(o++) === 1
    let t = v.getUint32(o, le); o += 4
    // EWKB flags (0x80000000 Z, 0x40000000 M, 0x20000000 SRID) and ISO offsets (1000 Z, 2000 M, 3000 ZM)
    let dims = 2
    if (t & 0x20000000) o += 4
    if (t & 0x80000000) dims++
    if (t & 0x40000000) dims++
    t &= 0x0fffffff
    if (t >= 3000) { dims = 4; t -= 3000 } else if (t >= 2000) { dims = 3; t -= 2000 } else if (t >= 1000) { dims = 3; t -= 1000 }
    const pt = (): Position => {
      const x = v.getFloat64(o, le), y = v.getFloat64(o + 8, le)
      o += 8 * dims
      return [x, y]
    }
    const n = () => { const k = v.getUint32(o, le); o += 4; return k }
    const pts = (): Position[] => Array.from({ length: n() }, pt)
    const rings = (): Position[][] => Array.from({ length: n() }, pts)
    switch (t) {
      case 1: return { type: 'Point', coordinates: pt() }
      case 2: return { type: 'LineString', coordinates: pts() }
      case 3: return { type: 'Polygon', coordinates: rings() }
      case 4: return { type: 'MultiPoint', coordinates: Array.from({ length: n() }, () => (read() as any).coordinates) }
      case 5: return { type: 'MultiLineString', coordinates: Array.from({ length: n() }, () => (read() as any).coordinates) }
      case 6: return { type: 'MultiPolygon', coordinates: Array.from({ length: n() }, () => (read() as any).coordinates) }
      case 7: return { type: 'GeometryCollection', geometries: Array.from({ length: n() }, read) }
      default: throw new Error(`unsupported WKB geometry type ${t}`)
    }
  }
  return read()
}
