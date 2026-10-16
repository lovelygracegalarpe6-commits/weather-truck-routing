import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { LonLat, PlanResponse } from '../api/types'
import { HeatmapRenderer } from '../map/heatmapRenderer'
import type { Status } from './usePlan'

const MAX_POINTS_PER_PATH = 1500
export const HEATMAP_HOURS = 48

function decimate(path: LonLat[], max: number): LonLat[] {
  if (path.length <= max) return path
  const step = (path.length - 1) / (max - 1)
  return Array.from({ length: max }, (_, i) => path[Math.round(i * step)])
}

interface HeatmapResult {
  status: 'success' | 'error'
  renderer: HeatmapRenderer | null
  error: string | null
  planKey: string
}

/** Loads the corridor forecast grid after each plan (routes render first, heatmap follows). */
export function useHeatmap(plan: PlanResponse | null) {
  const [result, setResult] = useState<HeatmapResult | null>(null)
  const planKey = plan?.generated_at ?? null

  useEffect(() => {
    if (!plan) return
    const ctrl = new AbortController()
    const paths = plan.routes.map((r) => decimate(r.path, MAX_POINTS_PER_PATH))
    api
      .heatmap(
        {
          paths,
          departure_utc: plan.trip.departure_utc,
          load_weight_lb: plan.trip.load_weight_lb,
          hours: HEATMAP_HOURS,
        },
        ctrl.signal,
      )
      .then((data) => {
        setResult({ status: 'success', renderer: new HeatmapRenderer(data, paths), error: null, planKey: plan.generated_at })
      })
      .catch((error: Error) => {
        if (error.name === 'AbortError') return
        setResult({ status: 'error', renderer: null, error: error.message, planKey: plan.generated_at })
      })
    return () => ctrl.abort()
  }, [plan])

  // A result only counts for the plan it was fetched for; until it arrives we're loading.
  const current = result !== null && result.planKey === planKey
  const status: Status = !plan ? 'idle' : current ? result.status : 'loading'
  return {
    status,
    error: current ? result.error : null,
    renderer: current ? result.renderer : null,
  }
}
