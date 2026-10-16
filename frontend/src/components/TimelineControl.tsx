import type { HeatmapLayerKey } from '../api/types'
import { formatDateTime, formatHoursOffset } from '../lib/format'
import { HEATMAP_LAYERS, legendGradient } from '../map/colors'
import type { Status } from '../hooks/usePlan'

interface Props {
  hours: number
  maxHours: number
  onHours: (hours: number) => void
  playing: boolean
  onPlaying: (playing: boolean) => void
  layer: HeatmapLayerKey
  onLayer: (layer: HeatmapLayerKey) => void
  visible: boolean
  onVisible: (visible: boolean) => void
  departureUtc: string
  timeZone: string
  status: Status
  error: string | null
}

const LAYERS: HeatmapLayerKey[] = ['risk', 'wind', 'rain', 'snow']

export function TimelineControl(props: Props) {
  const { hours, maxHours, onHours, playing, onPlaying, layer, onLayer, visible, onVisible } = props
  const spec = HEATMAP_LAYERS[layer]
  const min = spec.stops[0].value
  const max = spec.stops[spec.stops.length - 1].value
  const at = new Date(new Date(props.departureUtc).getTime() + hours * 3_600_000)

  return (
    <div className="timeline" role="group" aria-label="Forecast timeline">
      <div className="timeline-row">
        <button
          type="button"
          className="play"
          onClick={() => onPlaying(!playing)}
          aria-label={playing ? 'Pause forecast animation' : 'Play forecast animation'}
          disabled={props.status !== 'success'}
        >
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="slider">
          <input
            type="range"
            min={0}
            max={maxHours}
            step={0.25}
            value={hours}
            onChange={(e) => {
              onPlaying(false)
              onHours(Number(e.target.value))
            }}
            aria-label="Hours after departure"
            aria-valuetext={`${formatHoursOffset(hours)}, ${formatDateTime(at, props.timeZone)}`}
          />
          <div className="ticks" aria-hidden="true">
            {[0, 12, 24, 36, 48].map((h) => (
              <span key={h} style={{ left: `${(h / maxHours) * 100}%` }}>
                {h}h
              </span>
            ))}
          </div>
        </div>
        <div className="clock">
          <strong>{formatHoursOffset(hours)}</strong>
          <span>{formatDateTime(at, props.timeZone)}</span>
        </div>
      </div>

      <div className="timeline-row secondary">
        <div className="segmented small" role="radiogroup" aria-label="Heatmap layer">
          {LAYERS.map((key) => (
            <button
              key={key}
              type="button"
              role="radio"
              aria-checked={layer === key}
              className={layer === key ? 'on' : undefined}
              onClick={() => onLayer(key)}
            >
              {key === 'risk' ? 'Risk' : HEATMAP_LAYERS[key].label.split(' ')[0]}
            </button>
          ))}
        </div>
        <div className="legend" aria-label={`${spec.label} legend`}>
          <div className="legend-bar" style={{ background: legendGradient(spec.stops) }} />
          <div className="legend-ticks">
            {spec.ticks.map((t) => (
              <span key={t.value} style={{ left: `${((t.value - min) / (max - min)) * 100}%` }}>
                {t.label}
              </span>
            ))}
          </div>
          <span className="legend-unit">{spec.unit}</span>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={visible} onChange={(e) => onVisible(e.target.checked)} />
          Heatmap
        </label>
      </div>
      {props.status === 'loading' && <p className="timeline-status">Loading corridor forecast…</p>}
      {props.status === 'error' && <p className="timeline-status error">Heatmap unavailable: {props.error}</p>}
    </div>
  )
}
