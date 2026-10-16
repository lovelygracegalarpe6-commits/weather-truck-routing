// Mirrors the Django API contract (backend/planner/services/*.py).

export type RiskKey = 'low' | 'moderate' | 'high' | 'severe' | 'no_travel'

export interface Place {
  label: string
  lat: number
  lon: number
}

export interface CheckpointWeather {
  wind_mph: number
  gust_mph: number
  rain_in_hr: number
  snow_in_hr: number
}

export interface Checkpoint {
  index: number
  mile: number
  lat: number
  lon: number
  eta_utc: string
  eta_offset_s: number
  represents_miles: number
  level: RiskKey | null
  levels: { wind: RiskKey; rain: RiskKey; snow: RiskKey } | null
  reasons: string[]
  weather: CheckpointWeather | null
}

export interface RouteStats {
  miles_by_level: Record<RiskKey, number>
  unknown_miles: number
  average_risk: number | null
  max_level: RiskKey | null
}

export type LonLat = [number, number]

export interface Route {
  id: string
  name: string
  summary: string
  source: 'osrm' | 'osrm-via'
  distance_mi: number
  duration_s: number
  arrival_utc: string
  stats: RouteStats
  path: LonLat[]
  path_times_s: number[]
  checkpoints: Checkpoint[]
  rank: number
  recommended: boolean
}

export interface Comparison {
  other_route_id: string
  criterion: string
  text: string
}

export interface Trip {
  origin: Place
  destination: Place
  departure_utc: string
  timezone: string
  load_weight_lb: number
  interval_miles: IntervalMiles
  wind_metric: 'sustained' | 'gust'
  truck_max_speed_mph: number
}

export interface PlanResponse {
  trip: Trip
  recommendation: {
    route_id: string
    comparisons: Comparison[]
    warnings: string[]
  }
  routes: Route[]
  generated_at: string
}

export type IntervalMiles = 10 | 25 | 50

export interface PlanRequest {
  origin: Place
  destination: Place
  /** Wall-clock time at the origin ("YYYY-MM-DDTHH:MM"); null = leave now. */
  departure: string | null
  load_weight_lb: number
  interval_miles: IntervalMiles
}

export type HeatmapLayerKey = 'risk' | 'wind' | 'rain' | 'snow'

export interface HeatmapGrid {
  west: number
  south: number
  step: number
  nx: number
  ny: number
}

export interface HeatmapResponse {
  grid: HeatmapGrid
  /** Flat indices (iy * nx + ix) of the grid nodes inside the corridor. */
  nodes: number[]
  start_utc: string
  frame_seconds: number
  frames: number
  /** layers[key][frame][nodeIndex] */
  layers: Record<HeatmapLayerKey | 'gust', (number | null)[][]>
}

export interface HeatmapRequest {
  paths: LonLat[][]
  departure_utc: string
  load_weight_lb: number
  hours?: number
}
