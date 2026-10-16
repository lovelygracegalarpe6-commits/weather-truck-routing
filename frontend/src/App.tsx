import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from './api/client'
import type { HeatmapLayerKey, Place, PlanResponse } from './api/types'
import { type CheckpointRef, CheckpointTable } from './components/CheckpointTable'
import type { PlaceValue } from './components/PlaceInput'
import { Recommendation } from './components/Recommendation'
import { RouteCards } from './components/RouteCards'
import { RulesPanel } from './components/RulesPanel'
import { TimelineControl } from './components/TimelineControl'
import { TripForm, type TripFormState } from './components/TripForm'
import { HEATMAP_HOURS, useHeatmap } from './hooks/useHeatmap'
import { usePlan } from './hooks/usePlan'
import { usePlayback } from './hooks/usePlayback'
import { positionAtTime } from './lib/route'
import { HEATMAP_LAYERS } from './map/colors'
import { Icon } from './components/Icon'
import type { FocusRequest, HeatmapFrame, TruckMarker } from './map/MapView'

// MapLibre is most of the bundle. Loading the map as its own chunk lets the form paint
// while the map library downloads and compiles in parallel.
const MapView = lazy(() => import('./map/MapView').then((m) => ({ default: m.MapView })))

const place = (label: string, lat: number, lon: number): PlaceValue => ({ text: label, place: { label, lat, lon } })

const EXAMPLES: { label: string; origin: PlaceValue; destination: PlaceValue }[] = [
  {
    label: 'Chicago → Nashville',
    origin: place('Chicago, Illinois, US', 41.8781, -87.6298),
    destination: place('Nashville, Tennessee, US', 36.1627, -86.7816),
  },
  {
    label: 'Denver → Salt Lake City',
    origin: place('Denver, Colorado, US', 39.7392, -104.9903),
    destination: place('Salt Lake City, Utah, US', 40.7608, -111.891),
  },
  {
    label: 'Dallas → Houston',
    origin: place('Dallas, Texas, US', 32.7767, -96.797),
    destination: place('Houston, Texas, US', 29.7604, -95.3698),
  },
]

const INITIAL_FORM: TripFormState = {
  origin: { text: '', place: null },
  destination: { text: '', place: null },
  departure: '',
  loadWeight: '35000',
  interval: 25,
}

export default function App() {
  const [form, setForm] = useState<TripFormState>(INITIAL_FORM)
  const plan = usePlan()
  const heatmap = useHeatmap(plan.data)
  const [selection, setSelection] = useState<{ planKey: string; routeId: string } | null>(null)
  const [hours, setHours] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [layer, setLayer] = useState<HeatmapLayerKey>('risk')
  const [heatmapVisible, setHeatmapVisible] = useState(true)
  const [highlighted, setHighlighted] = useState<CheckpointRef | null>(null)
  const [focus, setFocus] = useState<FocusRequest | null>(null)
  usePlayback(playing, setHours, HEATMAP_HOURS)
  const mapArea = useRef<HTMLElement>(null)

  const data: PlanResponse | null = plan.data

  // On narrow screens the map sits below the form: bring it into view with new results.
  useEffect(() => {
    if (data && window.matchMedia('(max-width: 900px)').matches) {
      mapArea.current?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [data])
  // A new plan selects its recommended route until the user picks another.
  const selectedRouteId =
    data && selection?.planKey === data.generated_at ? selection.routeId : (data?.recommendation.route_id ?? null)
  const selectedRoute = data?.routes.find((r) => r.id === selectedRouteId) ?? null

  const selectRoute = useCallback(
    (routeId: string) => {
      if (data) setSelection({ planKey: data.generated_at, routeId })
    },
    [data],
  )

  const { run: runPlan, fail: failPlan } = plan
  const submit = useCallback(async (state: TripFormState) => {
    const resolve = async (value: PlaceValue, what: string, key: 'origin' | 'destination'): Promise<Place | null> => {
      if (value.place) return value.place
      const text = value.text.trim()
      if (!text) {
        failPlan(`Enter ${what}.`)
        return null
      }
      try {
        const { results } = await api.geocode(text)
        if (!results.length) {
          failPlan(`Couldn't find "${text}". Try a city name or full address.`)
          return null
        }
        setForm((f) => ({ ...f, [key]: { text: results[0].label, place: results[0] } }))
        return results[0]
      } catch (error) {
        failPlan((error as Error).message)
        return null
      }
    }

    const origin = await resolve(state.origin, 'an origin', 'origin')
    const destination = origin && (await resolve(state.destination, 'a destination', 'destination'))
    if (!origin || !destination) return
    const load = Number(state.loadWeight)
    if (state.loadWeight.trim() === '' || !Number.isFinite(load) || load < 0) {
      failPlan('Enter the load weight in pounds.')
      return
    }
    setPlaying(false)
    setHours(0)
    setHighlighted(null)
    void runPlan({
      origin,
      destination,
      departure: state.departure || null,
      load_weight_lb: load,
      interval_miles: state.interval,
    })
  }, [runPlan, failPlan])
  const submitForm = useCallback(() => void submit(form), [submit, form])

  const heatmapFrame: HeatmapFrame | null = useMemo(() => {
    const r = heatmap.renderer
    return r ? { ...r.render(layer, hours), corners: r.corners } : null
  }, [heatmap.renderer, layer, hours])

  const trucks: TruckMarker[] = useMemo(
    () =>
      data
        ? data.routes.map((r) => ({ routeId: r.id, ...positionAtTime(r.path, r.path_times_s, hours * 3600) }))
        : [],
    [data, hours],
  )

  const currentCheckpoint = useMemo(() => {
    if (!selectedRoute) return -1
    let index = -1
    for (const cp of selectedRoute.checkpoints) if (cp.eta_offset_s <= hours * 3600) index = cp.index
    return index
  }, [selectedRoute, hours])

  const probe = useCallback(
    (lon: number, lat: number) => {
      const r = heatmap.renderer
      if (!r || !heatmapVisible) return null
      const value = r.valueAt(layer, hours, lon, lat)
      if (value === null) return null
      const spec = HEATMAP_LAYERS[layer]
      return `${spec.label}: ${spec.format(value)}`
    },
    [heatmap.renderer, heatmapVisible, layer, hours],
  )

  const focusCheckpoint = useCallback(
    (ref: CheckpointRef) => {
      const cp = data?.routes.find((r) => r.id === ref.routeId)?.checkpoints[ref.index]
      if (!cp) return
      setHighlighted(ref)
      setFocus({ lon: cp.lon, lat: cp.lat, key: Date.now() })
      setPlaying(false)
      setHours(Math.min(cp.eta_offset_s / 3600, HEATMAP_HOURS))
    },
    [data],
  )

  const busy = plan.status === 'loading'

  return (
    <div className="app">
      <aside className="panel" aria-label="Trip planner">
        <header className="brand">
          <span className="brand-mark" aria-hidden="true">
            <Icon name="route" size={20} />
          </span>
          <div>
            <h1>Weather-Aware Truck Routing</h1>
            <p>The safest route, judged by the weather at the truck&apos;s ETA.</p>
          </div>
        </header>

        <TripForm value={form} onChange={setForm} onSubmit={submitForm} busy={busy} />

        <div className="examples">
          <span>Try</span>
          {EXAMPLES.map((ex) => (
            <button
              key={ex.label}
              type="button"
              className="chip"
              disabled={busy}
              onClick={() => {
                const next = { ...form, origin: ex.origin, destination: ex.destination }
                setForm(next)
                void submit(next)
              }}
            >
              {ex.label}
            </button>
          ))}
        </div>

        {plan.error && (
          <p className="error" role="alert">
            <Icon name="alert" size={16} /> {plan.error}
          </p>
        )}

        {data && (
          <div className={busy ? 'results stale' : 'results'} aria-busy={busy}>
            <Recommendation plan={data} />
            <RouteCards plan={data} selectedId={selectedRouteId} onSelect={selectRoute} />
            {selectedRoute && (
              <CheckpointTable
                route={selectedRoute}
                timeZone={data.trip.timezone}
                currentIndex={currentCheckpoint}
                onHover={setHighlighted}
                onFocus={focusCheckpoint}
              />
            )}
          </div>
        )}

        <RulesPanel truckMaxSpeedMph={data?.trip.truck_max_speed_mph} />
        <footer className="credits">
          Routing © OSRM · Weather © Open-Meteo · Map data © OpenStreetMap contributors · Basemap © OpenFreeMap
        </footer>
      </aside>

      <main className="map-stage" ref={mapArea}>
        <Suspense fallback={<div className="map-wrap map-placeholder" aria-hidden="true" />}>
          <MapView
            plan={data}
            selectedRouteId={selectedRouteId}
            onSelectRoute={selectRoute}
            heatmap={heatmapFrame}
            heatmapVisible={heatmapVisible}
            trucks={trucks}
            highlighted={highlighted}
            focus={focus}
            probe={probe}
          />
        </Suspense>
        {data ? (
          <TimelineControl
            hours={hours}
            maxHours={HEATMAP_HOURS}
            onHours={setHours}
            playing={playing}
            onPlaying={setPlaying}
            layer={layer}
            onLayer={setLayer}
            visible={heatmapVisible}
            onVisible={setHeatmapVisible}
            departureUtc={data.trip.departure_utc}
            timeZone={data.trip.timezone}
            status={heatmap.status}
            error={heatmap.error}
          />
        ) : (
          !busy && (
            <section className="welcome" aria-labelledby="welcome-title">
              <p className="eyebrow">
                <Icon name="cloud" size={14} /> Weather-aware routing
              </p>
              <h2 id="welcome-title">See the weather your truck will actually drive through.</h2>
              <ol className="steps">
                <li>
                  <span className="step-icon">
                    <Icon name="route" size={18} />
                  </span>
                  <span>
                    <strong>Three routes</strong> from the road network, fastest first.
                  </span>
                </li>
                <li>
                  <span className="step-icon">
                    <Icon name="clock" size={18} />
                  </span>
                  <span>
                    <strong>Forecast at every checkpoint</strong> for the hour the truck gets there.
                  </span>
                </li>
                <li>
                  <span className="step-icon">
                    <Icon name="shield" size={18} />
                  </span>
                  <span>
                    <strong>Ranked by risk</strong>: Severe miles, High miles, average risk, then time.
                  </span>
                </li>
              </ol>
              <p className="welcome-cta">Enter a trip, or pick one of the example trips to start.</p>
            </section>
          )
        )}
        {busy && (
          <div className="map-loading" role="status">
            <span className="radar" aria-hidden="true" />
            <span>
              <strong>Planning your trip</strong>
              Finding routes and checking the forecast at every checkpoint…
            </span>
          </div>
        )}
      </main>
    </div>
  )
}
