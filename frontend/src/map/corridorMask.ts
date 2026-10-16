import type { LonLat } from '../api/types'

const KM_PER_DEG = 111.32

export interface MaskGeometry {
  width: number
  height: number
  west: number
  east: number
  /** Latitude of each pixel row's centre, north to south (Mercator-spaced). */
  rowLats: Float64Array
}

/**
 * Per-pixel opacity for the heatmap corridor: 1 within half the radius of a route,
 * fading smoothly to 0 at `radiusKm`.
 *
 * Routes are rasterised into the image, then a two-pass chamfer distance transform
 * gives every pixel's approximate distance to the nearest route in km (rows carry their
 * own km scale because Mercator rows differ in height). The result follows the roads,
 * unlike the forecast grid's blocky node mask, and depends only on geometry, so it is
 * computed once per heatmap rather than per frame.
 */
export function corridorMask(geometry: MaskGeometry, paths: LonLat[][], radiusKm: number): Float32Array {
  const { width: w, height: h, west, east, rowLats } = geometry
  const n = w * h
  const dist = new Float32Array(n).fill(Number.POSITIVE_INFINITY)

  // Pixel-space position of a coordinate (continuous; pixel centres at integers).
  const lonToX = (lon: number) => ((lon - west) / (east - west)) * w - 0.5
  const north = rowLats[0]
  const south = rowLats[h - 1]
  const latToY = (lat: number) => {
    // Rows are Mercator-spaced: find the fractional row by binary search.
    if (lat >= north) return 0
    if (lat <= south) return h - 1
    let lo = 0
    let hi = h - 1
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1
      if (rowLats[mid] >= lat) lo = mid
      else hi = mid
    }
    return lo + (rowLats[lo] - lat) / (rowLats[lo] - rowLats[hi])
  }

  for (const path of paths) {
    for (let s = 0; s + 1 < path.length; s++) {
      const x0 = lonToX(path[s][0])
      const y0 = latToY(path[s][1])
      const x1 = lonToX(path[s + 1][0])
      const y1 = latToY(path[s + 1][1])
      const steps = Math.ceil(Math.max(Math.abs(x1 - x0), Math.abs(y1 - y0)) * 2) + 1
      for (let k = 0; k <= steps; k++) {
        const x = Math.round(x0 + ((x1 - x0) * k) / steps)
        const y = Math.round(y0 + ((y1 - y0) * k) / steps)
        if (x >= 0 && x < w && y >= 0 && y < h) dist[y * w + x] = 0
      }
    }
  }

  // Step costs in km: horizontal per row, vertical between a row and the one above it.
  const pixelLonDeg = (east - west) / w
  const dx = new Float32Array(h)
  const dy = new Float32Array(h)
  for (let y = 0; y < h; y++) {
    dx[y] = pixelLonDeg * KM_PER_DEG * Math.cos((rowLats[y] * Math.PI) / 180)
    dy[y] = y > 0 ? (rowLats[y - 1] - rowLats[y]) * KM_PER_DEG : 0
  }

  for (let y = 0; y < h; y++) {
    const ax = dx[y]
    const ay = dy[y]
    const diag = Math.hypot(ax, ay)
    for (let x = 0; x < w; x++) {
      const i = y * w + x
      let v = dist[i]
      if (x > 0 && dist[i - 1] + ax < v) v = dist[i - 1] + ax
      if (y > 0) {
        if (dist[i - w] + ay < v) v = dist[i - w] + ay
        if (x > 0 && dist[i - w - 1] + diag < v) v = dist[i - w - 1] + diag
        if (x < w - 1 && dist[i - w + 1] + diag < v) v = dist[i - w + 1] + diag
      }
      dist[i] = v
    }
  }
  for (let y = h - 1; y >= 0; y--) {
    const ax = dx[y]
    const ay = y < h - 1 ? dy[y + 1] : 0
    const diag = Math.hypot(ax, ay)
    for (let x = w - 1; x >= 0; x--) {
      const i = y * w + x
      let v = dist[i]
      if (x < w - 1 && dist[i + 1] + ax < v) v = dist[i + 1] + ax
      if (y < h - 1) {
        if (dist[i + w] + ay < v) v = dist[i + w] + ay
        if (x < w - 1 && dist[i + w + 1] + diag < v) v = dist[i + w + 1] + diag
        if (x > 0 && dist[i + w - 1] + diag < v) v = dist[i + w - 1] + diag
      }
      dist[i] = v
    }
  }

  const inner = radiusKm * 0.5
  const mask = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const t = Math.min(Math.max((radiusKm - dist[i]) / (radiusKm - inner), 0), 1)
    mask[i] = t * t * (3 - 2 * t)
  }
  return mask
}
