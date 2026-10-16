import { describe, expect, it } from 'vitest'
import type { Route } from '../api/types'
import { checkpointProgress, positionAtTime, riskGradient } from './route'
import { formatDuration, formatHoursOffset, formatMiles } from './format'

function route(checkpointLevels: (string | null)[]): Route {
  const path: [number, number][] = [
    [0, 0],
    [1, 0],
    [2, 0],
  ]
  const n = checkpointLevels.length
  return {
    id: 'A',
    name: 'Route A',
    summary: '',
    source: 'osrm',
    distance_mi: 138,
    duration_s: 7200,
    arrival_utc: '',
    stats: {
      miles_by_level: { low: 0, moderate: 0, high: 0, severe: 0, no_travel: 0 },
      unknown_miles: 0,
      average_risk: 0,
      max_level: 'low',
    },
    path,
    path_times_s: [0, 3600, 7200],
    checkpoints: checkpointLevels.map((level, i) => ({
      index: i,
      mile: 0,
      lat: 0,
      lon: 0,
      eta_utc: '',
      eta_offset_s: (7200 * i) / (n - 1),
      represents_miles: 0,
      level: level as Route['checkpoints'][number]['level'],
      levels: null,
      reasons: [],
      weather: null,
    })),
    rank: 1,
    recommended: true,
  }
}

describe('positionAtTime', () => {
  const r = route(['low', 'low'])

  it('interpolates along the path by drive time', () => {
    expect(positionAtTime(r.path, r.path_times_s, 1800)).toMatchObject({ lon: 0.5, lat: 0, progress: 0.25 })
    expect(positionAtTime(r.path, r.path_times_s, 5400).lon).toBeCloseTo(1.5)
  })

  it('clamps before departure and after arrival', () => {
    expect(positionAtTime(r.path, r.path_times_s, -10)).toMatchObject({ lon: 0, progress: 0 })
    expect(positionAtTime(r.path, r.path_times_s, 99999)).toMatchObject({ lon: 2, progress: 1 })
  })
})

describe('risk gradient', () => {
  const color = (level: string | null) => level ?? 'gray'

  it('places checkpoints by line progress', () => {
    expect(checkpointProgress(route(['low', 'low', 'low']))).toEqual([0, 0.5, 1])
  })

  it('switches color halfway between checkpoints and merges equal neighbours', () => {
    const expr = riskGradient(route(['low', 'low', 'severe', 'severe', 'low']), color)

    expect(expr).toEqual(['step', ['line-progress'], 'low', 0.375, 'severe', 0.875, 'low'])
  })

  it('collapses to a constant (still line-progress based) when the route shares one level', () => {
    expect(riskGradient(route(['high', 'high', 'high']), color)).toEqual([
      'interpolate',
      ['linear'],
      ['line-progress'],
      0,
      'high',
      1,
      'high',
    ])
  })
})

describe('formatting', () => {
  it('formats durations, miles and slider offsets', () => {
    expect(formatDuration(8 * 3600 + 52 * 60)).toBe('8h 52m')
    expect(formatDuration(25 * 60)).toBe('25m')
    expect(formatMiles(1234.4)).toBe('1,234 mi')
    expect(formatMiles(2.25)).toBe('2.3 mi')
    expect(formatHoursOffset(12.5)).toBe('+12h 30m')
    expect(formatHoursOffset(3)).toBe('+3h')
  })
})
