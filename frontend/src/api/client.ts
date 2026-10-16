import type { HeatmapRequest, HeatmapResponse, Place, PlanRequest, PlanResponse } from './types'

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')

const FIELD_LABELS: Record<string, string> = {
  origin: 'Origin',
  destination: 'Destination',
  departure: 'Departure',
  load_weight_lb: 'Load weight',
  interval_miles: 'Checkpoint interval',
  paths: 'Route geometry',
}

export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** Turn DRF error bodies ({detail} or {field: [msg]}) into one readable sentence. */
export function errorMessage(body: unknown, status: number): string {
  if (body && typeof body === 'object') {
    const record = body as Record<string, unknown>
    if (typeof record.detail === 'string') return record.detail
    const parts: string[] = []
    for (const [field, value] of Object.entries(record)) {
      const label = FIELD_LABELS[field] ?? field
      parts.push(`${label}: ${flatten(value).join(' ')}`)
    }
    if (parts.length) return parts.join(' · ')
  }
  return status >= 500 ? 'The server had a problem. Please try again.' : `Request failed (${status}).`
}

function flatten(value: unknown): string[] {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(flatten)
  if (value && typeof value === 'object') return Object.values(value).flatMap(flatten)
  return []
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...init.headers },
    })
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error
    throw new ApiError('Cannot reach the server. Check your connection and try again.', 0)
  }
  const body: unknown = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(errorMessage(body, response.status), response.status)
  return body as T
}

export const api = {
  geocode(query: string, signal?: AbortSignal): Promise<{ results: Place[] }> {
    return request(`/api/geocode/?q=${encodeURIComponent(query)}`, { signal })
  },
  plan(body: PlanRequest, signal?: AbortSignal): Promise<PlanResponse> {
    return request('/api/plan/', { method: 'POST', body: JSON.stringify(body), signal })
  },
  heatmap(body: HeatmapRequest, signal?: AbortSignal): Promise<HeatmapResponse> {
    return request('/api/heatmap/', { method: 'POST', body: JSON.stringify(body), signal })
  },
}
