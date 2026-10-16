import type { HeatmapLayerKey, HeatmapResponse } from '../api/types'
import { buildLut, type ColorLut, HEATMAP_LAYERS } from './colors'

/** Image corners for a MapLibre image source: top-left, top-right, bottom-right, bottom-left. */
export type Corners = [[number, number], [number, number], [number, number], [number, number]]

export interface RenderedFrame {
  pixels: Uint8ClampedArray<ArrayBuffer>
  width: number
  height: number
}

function mercatorY(lat: number): number {
  const s = Math.sin((lat * Math.PI) / 180)
  return 0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)
}

function latFromMercatorY(y: number): number {
  return (Math.atan(Math.sinh(Math.PI * (1 - 2 * y))) * 180) / Math.PI
}

// Pixels with almost no neighbouring data are skipped entirely.
const MIN_WEIGHT = 0.02
// Opacity fades with a blurred corridor-coverage field (smoothstep between these), so
// the corridor ends in soft rounded edges instead of grid-aligned rectangles.
const EDGE_START = 0.12
const EDGE_END = 0.6
const EDGE_SCALE = 1 / (EDGE_END - EDGE_START)

/** Separable [1 2 1] blur of a grid, clamped at the borders. */
function blur(grid: Float32Array, nx: number, ny: number): Float32Array {
  const tmp = new Float32Array(grid.length)
  const out = new Float32Array(grid.length)
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const l = grid[j * nx + Math.max(i - 1, 0)]
      const r = grid[j * nx + Math.min(i + 1, nx - 1)]
      tmp[j * nx + i] = (l + 2 * grid[j * nx + i] + r) / 4
    }
  }
  for (let j = 0; j < ny; j++) {
    for (let i = 0; i < nx; i++) {
      const d = tmp[Math.max(j - 1, 0) * nx + i]
      const u = tmp[Math.min(j + 1, ny - 1) * nx + i]
      out[j * nx + i] = (d + 2 * tmp[j * nx + i] + u) / 4
    }
  }
  return out
}

/**
 * Renders the corridor forecast grid to RGBA pixels for a MapLibre image source.
 *
 * - The image is laid out in Web-Mercator space (rows are re-projected) so it lines up
 *   with the basemap even across many degrees of latitude.
 * - Values are bilinearly interpolated between grid nodes; nodes outside the corridor
 *   are skipped and the remaining weights renormalised, so edges fade out softly.
 * - Fractional hours blend the two neighbouring hourly frames, which makes slider
 *   dragging and playback continuous instead of jumping hour to hour.
 * - Per-pixel sampling positions are computed once; a frame costs one pass over pixels.
 */
export class HeatmapRenderer {
  readonly width: number
  readonly height: number
  readonly corners: Corners
  readonly frames: number

  private readonly nx: number
  private readonly ny: number
  private readonly colI0: Int32Array
  private readonly colFx: Float32Array
  private readonly rowJ0: Int32Array
  private readonly rowFy: Float32Array
  private readonly fields = new Map<string, Float32Array>()
  private readonly luts = new Map<HeatmapLayerKey, ColorLut>()
  private readonly blendBuffer: Float32Array
  private readonly coverage: Float32Array
  private readonly buffers: [Uint8ClampedArray<ArrayBuffer>, Uint8ClampedArray<ArrayBuffer>]
  private flip = 0
  private readonly data: HeatmapResponse

  constructor(data: HeatmapResponse, pixelsPerCell = 8, maxSide = 512) {
    this.data = data
    const { west, south, step, nx, ny } = data.grid
    this.nx = nx
    this.ny = ny
    this.frames = data.frames
    const east = west + (nx - 1) * step
    const north = south + (ny - 1) * step
    const yNorth = mercatorY(north)
    const ySpan = mercatorY(south) - yNorth
    const xSpan = (east - west) / 360

    let width = Math.max(2, (nx - 1) * pixelsPerCell)
    let height = Math.max(2, Math.round((width * ySpan) / Math.max(xSpan, 1e-9)))
    const scale = Math.min(1, maxSide / Math.max(width, height))
    width = Math.max(2, Math.round(width * scale))
    height = Math.max(2, Math.round(height * scale))
    this.width = width
    this.height = height
    this.corners = [
      [west, north],
      [east, north],
      [east, south],
      [west, south],
    ]

    this.colI0 = new Int32Array(width)
    this.colFx = new Float32Array(width)
    for (let px = 0; px < width; px++) {
      const gx = ((px + 0.5) / width) * (nx - 1)
      const i0 = Math.max(0, Math.min(Math.floor(gx), nx - 2))
      this.colI0[px] = i0
      this.colFx[px] = nx > 1 ? gx - i0 : 0
    }
    this.rowJ0 = new Int32Array(height)
    this.rowFy = new Float32Array(height)
    for (let py = 0; py < height; py++) {
      const lat = latFromMercatorY(yNorth + ((py + 0.5) / height) * ySpan)
      const gy = (lat - south) / step
      const j0 = Math.max(0, Math.min(Math.floor(gy), ny - 2))
      this.rowJ0[py] = j0
      this.rowFy[py] = ny > 1 ? Math.min(Math.max(gy - j0, 0), 1) : 0
    }

    this.blendBuffer = new Float32Array(nx * ny)
    const mask = new Float32Array(nx * ny)
    for (const node of data.nodes) mask[node] = 1
    this.coverage = blur(blur(mask, nx, ny), nx, ny)
    this.buffers = [new Uint8ClampedArray(width * height * 4), new Uint8ClampedArray(width * height * 4)]
  }

  /** Full grid (NaN outside the corridor) for one layer at one hourly frame. */
  private field(layer: HeatmapLayerKey, frame: number): Float32Array {
    const key = `${layer}:${frame}`
    let field = this.fields.get(key)
    if (!field) {
      field = new Float32Array(this.nx * this.ny).fill(Number.NaN)
      const values = this.data.layers[layer][frame]
      const nodes = this.data.nodes
      for (let k = 0; k < nodes.length; k++) {
        const v = values[k]
        if (v !== null && v !== undefined) field[nodes[k]] = v
      }
      this.fields.set(key, field)
    }
    return field
  }

  /** Grid values at a fractional hour, blending neighbouring frames. */
  private fieldAt(layer: HeatmapLayerKey, hours: number): Float32Array {
    const h = Math.min(Math.max(hours, 0), this.frames - 1)
    const f0 = Math.floor(h)
    const a = h - f0
    const base = this.field(layer, f0)
    if (a < 1e-3 || f0 + 1 >= this.frames) return base
    const next = this.field(layer, f0 + 1)
    const out = this.blendBuffer
    for (let i = 0; i < out.length; i++) {
      const va = base[i]
      const vb = next[i]
      out[i] = Number.isNaN(va) ? vb : Number.isNaN(vb) ? va : va + (vb - va) * a
    }
    return out
  }

  private lut(layer: HeatmapLayerKey): ColorLut {
    let lut = this.luts.get(layer)
    if (!lut) {
      lut = buildLut(HEATMAP_LAYERS[layer].stops)
      this.luts.set(layer, lut)
    }
    return lut
  }

  render(layer: HeatmapLayerKey, hours: number): RenderedFrame {
    const src = this.fieldAt(layer, hours)
    const { min, max, rgba, size } = this.lut(layer)
    const scale = (size - 1) / (max - min)
    const last = size - 1
    const { nx, ny, width, height, colI0, colFx, rowJ0, rowFy, coverage } = this
    const dx = nx > 1 ? 1 : 0
    const out = this.buffers[this.flip]
    this.flip ^= 1 // double-buffer: the previous frame may still be referenced by the map

    // Hot loop: locals only, `v === v` is a NaN test without a call, smoothstep inlined.
    let o = 0
    for (let py = 0; py < height; py++) {
      const r0 = rowJ0[py] * nx
      const r1 = ny > 1 ? r0 + nx : r0
      const fy = rowFy[py]
      const gy = 1 - fy
      for (let px = 0; px < width; px++) {
        const a = r0 + colI0[px]
        const b = r1 + colI0[px]
        const fx = colFx[px]
        const gx = 1 - fx
        let acc = 0
        let wsum = 0
        let v = src[a]
        if (v === v) { acc += gx * gy * v; wsum += gx * gy }
        v = src[a + dx]
        if (v === v) { acc += fx * gy * v; wsum += fx * gy }
        v = src[b]
        if (v === v) { acc += gx * fy * v; wsum += gx * fy }
        v = src[b + dx]
        if (v === v) { acc += fx * fy * v; wsum += fx * fy }

        if (wsum < MIN_WEIGHT) {
          // Zero RGB too: buffers are reused and texture filtering would bleed stale colour.
          out[o] = out[o + 1] = out[o + 2] = out[o + 3] = 0
        } else {
          let idx = ((acc / wsum - min) * scale + 0.5) | 0
          idx = (idx < 0 ? 0 : idx > last ? last : idx) << 2
          // Fade out towards the corridor edge using the blurred coverage field.
          const cov =
            gx * gy * coverage[a] + fx * gy * coverage[a + dx] + gx * fy * coverage[b] + fx * fy * coverage[b + dx]
          let t = (cov - EDGE_START) * EDGE_SCALE
          t = t < 0 ? 0 : t > 1 ? 1 : t
          out[o] = rgba[idx]
          out[o + 1] = rgba[idx + 1]
          out[o + 2] = rgba[idx + 2]
          out[o + 3] = rgba[idx + 3] * t * t * (3 - 2 * t)
        }
        o += 4
      }
    }
    return { pixels: out, width, height }
  }

  /** Interpolated value at a map position (for the hover read-out), or null outside. */
  valueAt(layer: HeatmapLayerKey, hours: number, lon: number, lat: number): number | null {
    const { west, south, step } = this.data.grid
    const gx = (lon - west) / step
    const gy = (lat - south) / step
    if (gx < 0 || gy < 0 || gx > this.nx - 1 || gy > this.ny - 1) return null
    const src = this.fieldAt(layer, hours)
    const i0 = Math.min(Math.floor(gx), Math.max(this.nx - 2, 0))
    const j0 = Math.min(Math.floor(gy), Math.max(this.ny - 2, 0))
    const fx = gx - i0
    const fy = gy - j0
    let acc = 0
    let wsum = 0
    for (const [di, dj, w] of [
      [0, 0, (1 - fx) * (1 - fy)],
      [1, 0, fx * (1 - fy)],
      [0, 1, (1 - fx) * fy],
      [1, 1, fx * fy],
    ] as const) {
      const v = src[(j0 + dj) * this.nx + i0 + di]
      if (!Number.isNaN(v) && w > 0) {
        acc += w * v
        wsum += w
      }
    }
    return wsum > 0.25 ? acc / wsum : null
  }
}
