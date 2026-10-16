import { describe, expect, it } from 'vitest'
import { corridorMask } from './corridorMask'

// 100 x 100 px over 2 x 2 degrees at the equator (rows ~evenly spaced there).
const geometry = {
  width: 100,
  height: 100,
  west: 0,
  east: 2,
  rowLats: Float64Array.from({ length: 100 }, (_, y) => 1 - ((y + 0.5) / 100) * 2),
}
const at = (mask: Float32Array, x: number, y: number) => mask[y * 100 + x]

describe('corridorMask', () => {
  // A route along the equator through the middle row; 1 px is ~2.2 km.
  const mask = corridorMask(geometry, [[[0, 0], [2, 0]]], 40)

  it('is opaque on and near the route', () => {
    expect(at(mask, 50, 50)).toBe(1)
    expect(at(mask, 50, 50 - 8)).toBe(1) // ~18 km away: inside half the radius
  })

  it('fades smoothly to zero at the radius', () => {
    const profile = Array.from({ length: 25 }, (_, k) => at(mask, 50, 50 - k))
    for (let k = 1; k < profile.length; k++) expect(profile[k]).toBeLessThanOrEqual(profile[k - 1])
    expect(at(mask, 50, 50 - 14)).toBeGreaterThan(0) // ~31 km: fading
    expect(at(mask, 50, 50 - 14)).toBeLessThan(1)
    expect(at(mask, 50, 50 - 20)).toBe(0) // ~44 km: outside
  })

  it('follows the route shape instead of a grid', () => {
    const diagonal = corridorMask(geometry, [[[0, 1], [2, -1]]], 40)

    expect(at(diagonal, 50, 50)).toBe(1) // on the line
    expect(at(diagonal, 5, 95)).toBe(0) // far from the line in the opposite corner
    expect(at(diagonal, 95, 95)).toBe(1) // where the line ends (bottom right)
  })
})
