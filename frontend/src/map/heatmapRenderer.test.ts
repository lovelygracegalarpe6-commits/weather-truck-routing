import { describe, expect, it } from 'vitest'
import type { HeatmapResponse, LonLat } from '../api/types'
import { buildLut, HEATMAP_LAYERS } from './colors'
import { HeatmapRenderer } from './heatmapRenderer'

/** 3x3 grid; `risk` given per frame as 9 values (row-major from the south). */
function heatmap(riskFrames: (number | null)[][], nodes = [0, 1, 2, 3, 4, 5, 6, 7, 8]): HeatmapResponse {
  const empty = riskFrames.map(() => nodes.map(() => 0))
  return {
    grid: { west: -100, south: 40, step: 1, nx: 3, ny: 3, radius_km: 150 },
    nodes,
    start_utc: '2026-10-16T13:00:00Z',
    frame_seconds: 3600,
    frames: riskFrames.length,
    layers: { risk: riskFrames, wind: empty, gust: empty, rain: empty, snow: empty },
  }
}

const uniform = (v: number | null) => Array.from({ length: 9 }, () => v)
// A route through the middle of the grid, and one along its southern edge.
const MIDDLE: LonLat[][] = [[[-100, 41], [-98, 41]]]
const SOUTH: LonLat[][] = [[[-100, 40], [-98, 40]]]

describe('HeatmapRenderer', () => {
  it('maps the grid onto mercator-correct corners', () => {
    const r = new HeatmapRenderer(heatmap([uniform(0)]), MIDDLE)

    expect(r.corners).toEqual([
      [-100, 42],
      [-98, 42],
      [-98, 40],
      [-100, 40],
    ])
    expect(r.width).toBe(8) // (nx - 1) * 4 px per cell
    // Mercator stretches latitude: 2 deg tall at ~41N is taller than 2 deg wide.
    expect(r.height).toBeGreaterThan(r.width)
  })

  it('colors pixels from the lookup table', () => {
    const r = new HeatmapRenderer(heatmap([uniform(3)]), MIDDLE)
    const lut = buildLut(HEATMAP_LAYERS.risk.stops)
    const idx = Math.round(((3 - lut.min) / (lut.max - lut.min)) * (lut.size - 1)) * 4

    const { pixels } = r.render('risk', 0)

    const center = (Math.floor(r.height / 2) * r.width + Math.floor(r.width / 2)) * 4
    expect(Array.from(pixels.slice(center, center + 4))).toEqual(Array.from(lut.rgba.slice(idx, idx + 4)))
  })

  it('leaves pixels transparent where the corridor has no nodes', () => {
    // Only the southern row is in the corridor.
    const r = new HeatmapRenderer(heatmap([[4, 4, 4]], [0, 1, 2]), SOUTH)

    const { pixels } = r.render('risk', 0)

    expect(pixels[3]).toBe(0) // top-left pixel (north) is outside
    expect(pixels[pixels.length - 1]).toBeGreaterThan(0) // bottom-right (south) is inside
  })

  it('blends neighbouring hours for fractional times', () => {
    const r = new HeatmapRenderer(heatmap([uniform(0), uniform(4)]), MIDDLE)

    expect(r.valueAt('risk', 0, -99, 41)).toBe(0)
    expect(r.valueAt('risk', 0.5, -99, 41)).toBeCloseTo(2)
    expect(r.valueAt('risk', 1, -99, 41)).toBe(4)
    expect(r.valueAt('risk', 5, -99, 41)).toBe(4) // clamped to the last frame
  })

  it('interpolates bilinearly and ignores missing nodes', () => {
    const values = [0, 4, null, 0, 4, null, 0, 4, null]
    const r = new HeatmapRenderer(heatmap([values]), MIDDLE)

    expect(r.valueAt('risk', 0, -99.5, 41)).toBeCloseTo(2)
    expect(r.valueAt('risk', 0, -98.5, 41)).toBeCloseTo(4) // only the valid neighbour counts
    expect(r.valueAt('risk', 0, -90, 41)).toBeNull() // outside the grid
  })

  it('double-buffers frames so the map never reads a half-written image', () => {
    const r = new HeatmapRenderer(heatmap([uniform(1)]), MIDDLE)

    expect(r.render('risk', 0).pixels).not.toBe(r.render('risk', 0).pixels)
  })
})
