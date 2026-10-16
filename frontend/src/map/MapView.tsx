import type { Feature, FeatureCollection } from 'geojson'
import {
  type ExpressionSpecification,
  type GeoJSONSource,
  type CanvasSource,
  type CanvasSourceSpecification,
  type LngLatBoundsLike,
  Map as MapLibreMap,
  type MapLayerMouseEvent,
  type MapMouseEvent,
  Marker,
  NavigationControl,
  Popup,
  ScaleControl,
  setWorkerUrl,
} from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url'
import { useEffect, useRef, useState } from 'react'
import type { PlanResponse, Route } from '../api/types'
import type { CheckpointRef } from '../components/CheckpointTable'
import { formatDateTime } from '../lib/format'
import { riskGradient } from '../lib/route'
import { riskColor, riskLabel, RISK_META } from './colors'
import type { Corners, RenderedFrame } from './heatmapRenderer'

// MapLibre locates its (self-contained) worker relative to its own module, which breaks
// once a bundler relocates that module; point it at the file explicitly instead.
setWorkerUrl(workerUrl)

const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron'
const ROUTE_IDS = ['A', 'B', 'C'] as const
const BRAND = '#0b3d4b'
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] }

export interface TruckMarker {
  routeId: string
  lon: number
  lat: number
  progress: number
}

export interface HeatmapFrame extends RenderedFrame {
  corners: Corners
}

export interface FocusRequest {
  lon: number
  lat: number
  key: number
}

interface Props {
  plan: PlanResponse | null
  selectedRouteId: string | null
  onSelectRoute: (id: string) => void
  heatmap: HeatmapFrame | null
  heatmapVisible: boolean
  trucks: TruckMarker[]
  highlighted: CheckpointRef | null
  focus: FocusRequest | null
  /** Text describing the heatmap value under the cursor, if any. */
  probe: (lon: number, lat: number) => string | null
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`)
}

function checkpointFeatureId(routeId: string, index: number): number {
  return ROUTE_IDS.indexOf(routeId as (typeof ROUTE_IDS)[number]) * 100_000 + index
}

function popupHtml(route: Route, index: number, timeZone: string): string {
  const cp = route.checkpoints[index]
  const level = cp.level
  const chip = `<span class="risk-chip compact" style="background:${riskColor(level)};color:${
    level ? RISK_META[level].ink : '#fff'
  }">${riskLabel(level)}</span>`
  const w = cp.weather
  const weather = w
    ? `<div class="cp-weather">
         <span>Wind <b>${Math.round(w.wind_mph)}</b> mph <small>(gust ${Math.round(w.gust_mph)})</small></span>
         <span>Rain <b>${w.rain_in_hr.toFixed(2)}</b> in/hr</span>
         <span>Snow <b>${w.snow_in_hr.toFixed(2)}</b> in/hr</span>
       </div>`
    : '<div class="muted">No forecast for this time.</div>'
  const reasons = cp.reasons.length
    ? `<ul>${cp.reasons.map((r) => `<li>${escapeHtml(r)}</li>`).join('')}</ul>`
    : ''
  return `<div class="cp-popup">
    <div class="cp-head">${chip}<span>Route ${route.id} · mile ${Math.round(cp.mile)}</span></div>
    <div class="cp-eta">ETA ${escapeHtml(formatDateTime(cp.eta_utc, timeZone))}</div>
    ${weather}${reasons}
  </div>`
}

/** A crisp circular route-letter badge, drawn at device resolution. */
function badge(letter: string, fill: string): { image: ImageData; pixelRatio: number } {
  const ratio = Math.max(1, Math.ceil(window.devicePixelRatio || 1))
  const size = 22 * ratio
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = size
  const ctx = canvas.getContext('2d')!
  ctx.fillStyle = '#ffffff'
  ctx.beginPath()
  ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = fill
  ctx.beginPath()
  ctx.arc(size / 2, size / 2, size / 2 - 2 * ratio, 0, Math.PI * 2)
  ctx.fill()
  ctx.fillStyle = '#ffffff'
  ctx.font = `700 ${12 * ratio}px system-ui, sans-serif`
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'
  ctx.fillText(letter, size / 2, size / 2 + ratio)
  return { image: ctx.getImageData(0, 0, size, size), pixelRatio: ratio }
}

function addLayers(map: MapLibreMap) {
  for (const id of ROUTE_IDS) {
    for (const [suffix, fill] of [['', BRAND], ['-dim', '#667085']] as const) {
      const { image, pixelRatio } = badge(id, fill)
      map.addImage(`badge-${id}${suffix}`, image, { pixelRatio })
    }
  }
  const beforeLabels = map.getStyle().layers.find((l) => l.type === 'symbol')?.id

  // A canvas source (not an image source) so frames can be updated in place; see the
  // heatmap effect in MapView.
  map.addSource('heatmap', {
    type: 'canvas',
    canvas: document.createElement('canvas'),
    animate: false,
    coordinates: [
      [-100, 41],
      [-99, 41],
      [-99, 40],
      [-100, 40],
    ],
  } as CanvasSourceSpecification)
  map.addLayer(
    {
      id: 'heatmap',
      type: 'raster',
      source: 'heatmap',
      layout: { visibility: 'none' },
      paint: { 'raster-opacity': 0.9, 'raster-fade-duration': 0, 'raster-resampling': 'linear' },
    },
    beforeLabels,
  )

  for (const id of ROUTE_IDS) {
    const source = `route-${id}`
    map.addSource(source, { type: 'geojson', data: EMPTY, lineMetrics: true })
    map.addLayer(
      {
        id: `${source}-casing`,
        type: 'line',
        source,
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': '#ffffff', 'line-width': 7, 'line-opacity': 0.95 },
      },
      beforeLabels,
    )
    map.addLayer(
      {
        id: source,
        type: 'line',
        source,
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-width': 4, 'line-gradient': ['interpolate', ['linear'], ['line-progress'], 0, '#98a2b3', 1, '#98a2b3'] },
      },
      beforeLabels,
    )
    map.addLayer({
      id: `${source}-hit`,
      type: 'line',
      source,
      paint: { 'line-width': 18, 'line-opacity': 0 },
    })
    map.addLayer({
      id: `${source}-label`,
      type: 'symbol',
      source,
      layout: {
        'symbol-placement': 'line-center',
        'icon-image': `badge-${id}`,
        'icon-rotation-alignment': 'viewport',
        'icon-allow-overlap': true,
      },
    })
  }

  map.addSource('checkpoints', { type: 'geojson', data: EMPTY })
  const hovered: ExpressionSpecification = ['boolean', ['feature-state', 'hover'], false]
  map.addLayer({
    id: 'checkpoints',
    type: 'circle',
    source: 'checkpoints',
    paint: {
      'circle-color': ['get', 'color'],
      'circle-radius': [
        'interpolate',
        ['linear'],
        ['zoom'],
        4,
        ['case', hovered, 7, ['get', 'selected'], 3.5, 2.2],
        9,
        ['case', hovered, 11, ['get', 'selected'], 7, 4],
      ],
      'circle-stroke-color': ['case', hovered, BRAND, '#ffffff'],
      'circle-stroke-width': ['case', hovered, 3, 1.2],
      'circle-opacity': ['case', ['get', 'selected'], 1, 0.6],
      'circle-stroke-opacity': ['case', ['get', 'selected'], 1, 0.6],
    },
  })

  map.addSource('endpoints', { type: 'geojson', data: EMPTY })
  map.addLayer({
    id: 'endpoints',
    type: 'circle',
    source: 'endpoints',
    paint: {
      'circle-radius': 7,
      'circle-color': ['match', ['get', 'kind'], 'origin', '#ffffff', BRAND],
      'circle-stroke-color': BRAND,
      'circle-stroke-width': 3,
    },
  })
}

export function MapView(props: Props) {
  const { plan, selectedRouteId, heatmap, heatmapVisible, trucks, highlighted, focus } = props
  const container = useRef<HTMLDivElement>(null)
  const probeEl = useRef<HTMLDivElement>(null)
  const mapRef = useRef<MapLibreMap | null>(null)
  const popupRef = useRef<Popup | null>(null)
  const hoverRef = useRef<number | null>(null)
  const cornersRef = useRef<Corners | null>(null)
  const truckMarkers = useRef(new Map<string, Marker>())
  const propsRef = useRef(props)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    propsRef.current = props
  })

  // Create the map once.
  useEffect(() => {
    const map = new MapLibreMap({
      container: container.current!,
      style: STYLE_URL,
      center: [-96.5, 38.5],
      zoom: 3.6,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    })
    map.touchZoomRotate.disableRotation()
    map.addControl(new NavigationControl({ showCompass: false }), 'top-right')
    map.addControl(new ScaleControl({ unit: 'imperial' }), 'bottom-right')
    const popup = new Popup({ closeButton: false, closeOnClick: false, maxWidth: '300px', offset: 10 })
    popupRef.current = popup

    const setHover = (id: number | null) => {
      if (hoverRef.current !== null) map.setFeatureState({ source: 'checkpoints', id: hoverRef.current }, { hover: false })
      hoverRef.current = id
      if (id !== null) map.setFeatureState({ source: 'checkpoints', id }, { hover: true })
    }

    map.on('load', () => {
      addLayers(map)

      map.on('mousemove', 'checkpoints', (e: MapLayerMouseEvent) => {
        const feature = e.features?.[0]
        const current = propsRef.current.plan
        if (!feature || !current) return
        const { routeId, index } = feature.properties as { routeId: string; index: number }
        const route = current.routes.find((r) => r.id === routeId)
        if (!route) return
        map.getCanvas().style.cursor = 'pointer'
        setHover(feature.id as number)
        const cp = route.checkpoints[index]
        popup.setLngLat([cp.lon, cp.lat]).setHTML(popupHtml(route, index, current.trip.timezone)).addTo(map)
      })
      map.on('mouseleave', 'checkpoints', () => {
        map.getCanvas().style.cursor = ''
        setHover(null)
        popup.remove()
      })
      for (const id of ROUTE_IDS) {
        map.on('click', `route-${id}-hit`, () => propsRef.current.onSelectRoute(id))
        map.on('mouseenter', `route-${id}-hit`, () => (map.getCanvas().style.cursor = 'pointer'))
        map.on('mouseleave', `route-${id}-hit`, () => (map.getCanvas().style.cursor = ''))
      }
      setReady(true)
    })

    // Heatmap read-out follows the cursor without re-rendering React.
    map.on('mousemove', (e: MapMouseEvent) => {
      const el = probeEl.current
      if (!el) return
      const text = propsRef.current.probe(e.lngLat.lng, e.lngLat.lat)
      el.textContent = text ?? ''
      el.style.display = text ? 'block' : 'none'
    })
    map.on('mouseout', () => {
      if (probeEl.current) probeEl.current.style.display = 'none'
    })

    mapRef.current = map
    return () => {
      popup.remove()
      map.remove()
      mapRef.current = null
      setReady(false)
    }
  }, [])

  // Routes, endpoints and camera for a new plan.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    for (const id of ROUTE_IDS) {
      const route = plan?.routes.find((r) => r.id === id)
      const source = map.getSource(`route-${id}`) as GeoJSONSource
      source.setData(
        route
          ? { type: 'Feature', properties: { id }, geometry: { type: 'LineString', coordinates: route.path } }
          : EMPTY,
      )
      if (route) {
        map.setPaintProperty(`route-${id}`, 'line-gradient', riskGradient(route, riskColor) as ExpressionSpecification)
      }
    }
    const endpoints = map.getSource('endpoints') as GeoJSONSource
    if (!plan) {
      endpoints.setData(EMPTY)
      return
    }
    const { origin, destination } = plan.trip
    endpoints.setData({
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', properties: { kind: 'origin' }, geometry: { type: 'Point', coordinates: [origin.lon, origin.lat] } },
        {
          type: 'Feature',
          properties: { kind: 'destination' },
          geometry: { type: 'Point', coordinates: [destination.lon, destination.lat] },
        },
      ],
    })
    const coords = plan.routes.flatMap((r) => r.path)
    const lons = coords.map((c) => c[0])
    const lats = coords.map((c) => c[1])
    const bounds: LngLatBoundsLike = [
      [Math.min(...lons), Math.min(...lats)],
      [Math.max(...lons), Math.max(...lats)],
    ]
    map.fitBounds(bounds, { padding: { top: 60, bottom: 190, left: 60, right: 60 }, duration: 900 })
  }, [plan, ready])

  // Selection: emphasise the selected route and its checkpoints.
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    const beforeLabels = map.getStyle().layers.find((l) => l.type === 'symbol')?.id
    // Re-stack so the selected route is drawn above the others (but below map labels).
    const ordered = [...ROUTE_IDS.filter((id) => id !== selectedRouteId), ...ROUTE_IDS.filter((id) => id === selectedRouteId)]
    for (const id of ordered) {
      const selected = id === selectedRouteId
      map.setPaintProperty(`route-${id}`, 'line-width', selected ? 6 : 3.5)
      map.setPaintProperty(`route-${id}`, 'line-opacity', selected ? 1 : 0.55)
      map.setPaintProperty(`route-${id}-casing`, 'line-width', selected ? 10 : 6)
      map.setLayoutProperty(`route-${id}-label`, 'icon-image', selected ? `badge-${id}` : `badge-${id}-dim`)
      map.moveLayer(`route-${id}-casing`, beforeLabels)
      map.moveLayer(`route-${id}`, beforeLabels)
    }
    const features: Feature[] = (plan?.routes ?? []).flatMap((route) =>
      route.checkpoints.map((cp) => ({
        type: 'Feature' as const,
        id: checkpointFeatureId(route.id, cp.index),
        properties: {
          routeId: route.id,
          index: cp.index,
          color: riskColor(cp.level),
          selected: route.id === selectedRouteId,
        },
        geometry: { type: 'Point' as const, coordinates: [cp.lon, cp.lat] },
      })),
    )
    // Selected route's checkpoints last so they draw on top.
    features.sort((a, b) => Number(a.properties!.selected) - Number(b.properties!.selected))
    ;(map.getSource('checkpoints') as GeoJSONSource).setData({ type: 'FeatureCollection', features })
  }, [plan, selectedRouteId, ready])

  // Heatmap frame. The pixels are drawn into the canvas source's canvas, and play() +
  // pause() copies it into the existing GPU texture once. ImageSource.updateImage was
  // used before, but it re-lays out the source's tiles and fires metadata events on every
  // call, which slowed playback from ~20 to ~8 fps within seconds (perf/README.md).
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    const show = heatmapVisible && heatmap !== null
    map.setLayoutProperty('heatmap', 'visibility', show ? 'visible' : 'none')
    if (!heatmap) {
      cornersRef.current = null
      return
    }
    if (!show) return // nothing to draw while hidden
    const source = map.getSource('heatmap') as CanvasSource
    const canvas = source.getCanvas()
    if (canvas.width !== heatmap.width || canvas.height !== heatmap.height) {
      canvas.width = heatmap.width
      canvas.height = heatmap.height
    }
    canvas.getContext('2d')!.putImageData(new ImageData(heatmap.pixels, heatmap.width, heatmap.height), 0, 0)
    if (cornersRef.current !== heatmap.corners) {
      cornersRef.current = heatmap.corners
      source.setCoordinates(heatmap.corners)
    }
    source.play()
    source.pause()
  }, [heatmap, heatmapVisible, ready])

  // Truck positions at the slider time. DOM markers rather than a GeoJSON layer: moving
  // three markers is a CSS transform, while setData on every frame meant a worker round
  // trip, a tile reload and label placement each time (perf/README.md).
  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready) return
    const markers = truckMarkers.current
    const seen = new Set<string>()
    for (const t of trucks) {
      seen.add(t.routeId)
      let marker = markers.get(t.routeId)
      if (!marker) {
        const el = document.createElement('div')
        el.className = 'truck-marker'
        el.textContent = t.routeId
        el.setAttribute('aria-hidden', 'true')
        marker = new Marker({ element: el }).setLngLat([t.lon, t.lat]).addTo(map)
        markers.set(t.routeId, marker)
      } else {
        marker.setLngLat([t.lon, t.lat])
      }
      marker.getElement().classList.toggle('selected', t.routeId === selectedRouteId)
    }
    for (const [id, marker] of markers) {
      if (!seen.has(id)) {
        marker.remove()
        markers.delete(id)
      }
    }
  }, [trucks, selectedRouteId, ready])

  // Checkpoint highlighted from the table.
  useEffect(() => {
    const map = mapRef.current
    const popup = popupRef.current
    if (!map || !ready || !popup) return
    if (hoverRef.current !== null) {
      map.setFeatureState({ source: 'checkpoints', id: hoverRef.current }, { hover: false })
      hoverRef.current = null
    }
    const route = highlighted && plan?.routes.find((r) => r.id === highlighted.routeId)
    if (!highlighted || !route || !plan) {
      popup.remove()
      return
    }
    const id = checkpointFeatureId(route.id, highlighted.index)
    hoverRef.current = id
    map.setFeatureState({ source: 'checkpoints', id }, { hover: true })
    const cp = route.checkpoints[highlighted.index]
    popup.setLngLat([cp.lon, cp.lat]).setHTML(popupHtml(route, highlighted.index, plan.trip.timezone)).addTo(map)
  }, [highlighted, plan, ready])

  useEffect(() => {
    const map = mapRef.current
    if (!map || !ready || !focus) return
    map.flyTo({ center: [focus.lon, focus.lat], zoom: Math.max(map.getZoom(), 8), duration: 800 })
  }, [focus, ready])

  return (
    <div className="map-wrap">
      <div ref={container} className="map" role="region" aria-label="Route map" />
      <div ref={probeEl} className="probe" aria-hidden="true" />
    </div>
  )
}
