import type { LonLat, Route } from '../api/types'

export interface TrackPosition {
  lon: number
  lat: number
  /** 0 before departure .. 1 at the destination */
  progress: number
}

/** Index i such that values[i] <= x < values[i+1] (clamped to a valid segment). */
function segmentIndex(values: number[], x: number): number {
  let lo = 0
  let hi = values.length - 1
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1
    if (values[mid] <= x) lo = mid
    else hi = mid
  }
  return lo
}

/** Where the truck is after driving `seconds`, interpolated along the route path. */
export function positionAtTime(path: LonLat[], times: number[], seconds: number): TrackPosition {
  const total = times[times.length - 1]
  const t = Math.min(Math.max(seconds, 0), total)
  const i = segmentIndex(times, t)
  const span = times[i + 1] - times[i]
  const f = span > 0 ? (t - times[i]) / span : 0
  const [lon0, lat0] = path[i]
  const [lon1, lat1] = path[Math.min(i + 1, path.length - 1)]
  return {
    lon: lon0 + (lon1 - lon0) * f,
    lat: lat0 + (lat1 - lat0) * f,
    progress: total > 0 ? t / total : 1,
  }
}

function mercatorY(lat: number): number {
  const s = Math.sin((lat * Math.PI) / 180)
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)
}

/** Cumulative Web-Mercator length at each vertex: what MapLibre's line-progress measures. */
export function mercatorLengths(path: LonLat[]): number[] {
  const out = [0]
  for (let i = 1; i < path.length; i++) {
    const dx = (path[i][0] - path[i - 1][0]) / 360
    const dy = mercatorY(path[i][1]) - mercatorY(path[i - 1][1])
    out.push(out[i - 1] + Math.hypot(dx, dy))
  }
  return out
}

/** line-progress (0..1) of each checkpoint, located via its drive-time offset. */
export function checkpointProgress(route: Route): number[] {
  const lengths = mercatorLengths(route.path)
  const total = lengths[lengths.length - 1] || 1
  const times = route.path_times_s
  return route.checkpoints.map((cp) => {
    const i = segmentIndex(times, cp.eta_offset_s)
    const span = times[i + 1] - times[i]
    const f = span > 0 ? Math.min(Math.max((cp.eta_offset_s - times[i]) / span, 0), 1) : 0
    const along = lengths[i] + (lengths[Math.min(i + 1, lengths.length - 1)] - lengths[i]) * f
    return along / total
  })
}

/**
 * A MapLibre `line-gradient` expression over line-progress that paints each stretch
 * of the route in the color of the checkpoint it is nearest to. line-gradient only
 * accepts line-progress expressions, so a single color is still expressed as one.
 */
export function riskGradient(route: Route, colorOf: (level: Route['checkpoints'][number]['level']) => string): unknown {
  const progress = checkpointProgress(route)
  const colors = route.checkpoints.map((cp) => colorOf(cp.level))
  const constant = (color: string) => ['interpolate', ['linear'], ['line-progress'], 0, color, 1, color]
  if (colors.length === 0) return constant(colorOf(null))
  const expression: unknown[] = ['step', ['line-progress'], colors[0]]
  let last = 0
  for (let i = 1; i < colors.length; i++) {
    const boundary = (progress[i - 1] + progress[i]) / 2
    if (boundary <= last || boundary >= 1) continue
    if (colors[i] === expression[expression.length - 1]) continue // merge equal neighbours
    expression.push(boundary, colors[i])
    last = boundary
  }
  return expression.length === 3 ? constant(colors[0]) : expression
}
