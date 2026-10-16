import type { HeatmapLayerKey, RiskKey } from '../api/types'

export const RISK_KEYS: RiskKey[] = ['low', 'moderate', 'high', 'severe', 'no_travel']

export const RISK_META: Record<RiskKey, { label: string; color: string; ink: string }> = {
  low: { label: 'Low', color: '#2f9e5b', ink: '#ffffff' },
  moderate: { label: 'Moderate', color: '#e9b308', ink: '#1f2328' },
  high: { label: 'High', color: '#f08c00', ink: '#1f2328' },
  severe: { label: 'Severe', color: '#e03131', ink: '#ffffff' },
  no_travel: { label: 'No Travel', color: '#7b2cbf', ink: '#ffffff' },
}

export const UNKNOWN_COLOR = '#98a2b3'

export function riskColor(level: RiskKey | null): string {
  return level ? RISK_META[level].color : UNKNOWN_COLOR
}

export function riskLabel(level: RiskKey | null): string {
  return level ? RISK_META[level].label : 'No forecast'
}

// --- Heatmap color scales ---------------------------------------------------------------

type RGB = [number, number, number]

export interface RampStop {
  value: number
  color: RGB
  alpha: number
}

export interface HeatmapLayerSpec {
  key: HeatmapLayerKey
  label: string
  unit: string
  stops: RampStop[]
  /** Legend ticks; for raw weather these are the risk thresholds. */
  ticks: { value: number; label: string }[]
  format: (value: number) => string
}

function hex(color: string): RGB {
  const n = parseInt(color.slice(1), 16)
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255]
}

const risk = (key: RiskKey) => hex(RISK_META[key].color)

export const HEATMAP_LAYERS: Record<HeatmapLayerKey, HeatmapLayerSpec> = {
  risk: {
    key: 'risk',
    label: 'Risk (for this load)',
    unit: '',
    stops: [
      { value: 0, color: risk('low'), alpha: 0.12 },
      { value: 1, color: risk('moderate'), alpha: 0.45 },
      { value: 2, color: risk('high'), alpha: 0.55 },
      { value: 3, color: risk('severe'), alpha: 0.62 },
      { value: 4, color: risk('no_travel'), alpha: 0.7 },
    ],
    ticks: [
      { value: 0, label: 'Low' },
      { value: 1, label: 'Mod' },
      { value: 2, label: 'High' },
      { value: 3, label: 'Severe' },
      { value: 4, label: 'No travel' },
    ],
    format: (v) => RISK_META[RISK_KEYS[Math.round(Math.min(Math.max(v, 0), 4))]].label,
  },
  wind: {
    key: 'wind',
    label: 'Wind speed',
    unit: 'mph',
    stops: [
      { value: 0, color: hex('#9ec5e8'), alpha: 0 },
      { value: 12, color: hex('#9ec5e8'), alpha: 0.18 },
      { value: 25, color: risk('moderate'), alpha: 0.45 },
      { value: 35, color: risk('high'), alpha: 0.55 },
      { value: 45, color: risk('severe'), alpha: 0.62 },
      { value: 55, color: risk('no_travel'), alpha: 0.7 },
      { value: 70, color: hex('#3c096c'), alpha: 0.75 },
    ],
    ticks: [25, 35, 45, 55].map((v) => ({ value: v, label: String(v) })),
    format: (v) => `${v.toFixed(0)} mph`,
  },
  rain: {
    key: 'rain',
    label: 'Rain',
    unit: 'in/hr',
    stops: [
      { value: 0, color: hex('#bfdbfe'), alpha: 0 },
      { value: 0.01, color: hex('#bfdbfe'), alpha: 0.25 },
      { value: 0.1, color: hex('#60a5fa'), alpha: 0.45 },
      { value: 0.25, color: hex('#2563eb'), alpha: 0.55 },
      { value: 0.5, color: hex('#7c3aed'), alpha: 0.62 },
      { value: 1.0, color: hex('#c026d3'), alpha: 0.7 },
      { value: 1.3, color: hex('#86198f'), alpha: 0.75 },
    ],
    ticks: [0.1, 0.25, 0.5, 1.0].map((v) => ({ value: v, label: v.toFixed(2) })),
    format: (v) => `${v.toFixed(2)} in/hr`,
  },
  snow: {
    key: 'snow',
    label: 'Snowfall',
    unit: 'in/hr',
    stops: [
      { value: 0, color: hex('#e0f2fe'), alpha: 0 },
      { value: 0.05, color: hex('#bae6fd'), alpha: 0.3 },
      { value: 0.5, color: hex('#38bdf8'), alpha: 0.5 },
      { value: 1.0, color: hex('#6366f1'), alpha: 0.58 },
      { value: 2.0, color: hex('#7c3aed'), alpha: 0.65 },
      { value: 3.0, color: hex('#a21caf'), alpha: 0.72 },
      { value: 3.5, color: hex('#701a75'), alpha: 0.75 },
    ],
    ticks: [0.5, 1, 2, 3].map((v) => ({ value: v, label: String(v) })),
    format: (v) => `${v.toFixed(2)} in/hr`,
  },
}

export interface ColorLut {
  min: number
  max: number
  /** size * 4 RGBA bytes (alpha already scaled to 0..255) */
  rgba: Uint8ClampedArray
  size: number
}

/** Precompute a lookup table so per-pixel coloring is a single array read. */
export function buildLut(stops: RampStop[], size = 512): ColorLut {
  const min = stops[0].value
  const max = stops[stops.length - 1].value
  const rgba = new Uint8ClampedArray(size * 4)
  let s = 0
  for (let i = 0; i < size; i++) {
    const v = min + ((max - min) * i) / (size - 1)
    while (s < stops.length - 2 && v > stops[s + 1].value) s++
    const a = stops[s]
    const b = stops[s + 1]
    const f = b.value > a.value ? Math.min(Math.max((v - a.value) / (b.value - a.value), 0), 1) : 0
    rgba[i * 4] = a.color[0] + (b.color[0] - a.color[0]) * f
    rgba[i * 4 + 1] = a.color[1] + (b.color[1] - a.color[1]) * f
    rgba[i * 4 + 2] = a.color[2] + (b.color[2] - a.color[2]) * f
    rgba[i * 4 + 3] = 255 * (a.alpha + (b.alpha - a.alpha) * f)
  }
  return { min, max, rgba, size }
}

/** CSS gradient for the legend, matching the LUT (alpha raised so it reads on white). */
export function legendGradient(stops: RampStop[]): string {
  const min = stops[0].value
  const max = stops[stops.length - 1].value
  const parts = stops.map((s) => {
    const pct = ((s.value - min) / (max - min)) * 100
    const alpha = Math.min(1, 0.25 + s.alpha * 1.1)
    return `rgba(${s.color[0]}, ${s.color[1]}, ${s.color[2]}, ${alpha.toFixed(2)}) ${pct.toFixed(1)}%`
  })
  return `linear-gradient(to right, ${parts.join(', ')})`
}
