import { memo } from 'react'
import type { Checkpoint, Route } from '../api/types'
import { formatDateTime } from '../lib/format'
import { RiskChip } from './RiskChip'

export interface CheckpointRef {
  routeId: string
  index: number
}

interface Props {
  route: Route
  timeZone: string
  /** Index of the checkpoint the truck has most recently passed at the slider time. */
  currentIndex: number
  onHover: (ref: CheckpointRef | null) => void
  onFocus: (ref: CheckpointRef) => void
}

interface RowProps {
  routeId: string
  checkpoint: Checkpoint
  current: boolean
  timeZone: string
  onHover: (ref: CheckpointRef | null) => void
  onFocus: (ref: CheckpointRef) => void
}

/** Memoised so moving the time slider only re-renders the rows whose "current" flag changes. */
const CheckpointRow = memo(function CheckpointRow({ routeId, checkpoint: cp, current, timeZone, onHover, onFocus }: RowProps) {
  const w = cp.weather
  return (
    <tr
      className={current ? 'current' : undefined}
      onMouseEnter={() => onHover({ routeId, index: cp.index })}
      onClick={() => onFocus({ routeId, index: cp.index })}
      title={cp.reasons.join('; ') || undefined}
    >
      <td className="num">{Math.round(cp.mile)}</td>
      <td>{formatDateTime(cp.eta_utc, timeZone)}</td>
      <td>
        <RiskChip level={cp.level} compact />
      </td>
      <td className="num">
        {w ? (
          <>
            {Math.round(w.wind_mph)} <span className="muted">({Math.round(w.gust_mph)})</span>
          </>
        ) : (
          '—'
        )}
      </td>
      <td className="num">{w ? w.rain_in_hr.toFixed(2) : '—'}</td>
      <td className="num">{w ? w.snow_in_hr.toFixed(2) : '—'}</td>
    </tr>
  )
})

export const CheckpointTable = memo(function CheckpointTable({
  route,
  timeZone,
  currentIndex,
  onHover,
  onFocus,
}: Props) {
  return (
    <section className="card checkpoints" aria-labelledby="cp-title">
      <h3 id="cp-title">
        Checkpoints · Route {route.id} <span className="muted">({route.checkpoints.length})</span>
      </h3>
      <div className="table-scroll" onMouseLeave={() => onHover(null)}>
        <table>
          <thead>
            <tr>
              <th scope="col">Mile</th>
              <th scope="col">ETA</th>
              <th scope="col">Risk</th>
              <th scope="col" title="Sustained wind (gusts)">
                Wind
              </th>
              <th scope="col">Rain</th>
              <th scope="col">Snow</th>
            </tr>
          </thead>
          <tbody>
            {route.checkpoints.map((cp) => (
              <CheckpointRow
                key={cp.index}
                routeId={route.id}
                checkpoint={cp}
                current={cp.index === currentIndex}
                timeZone={timeZone}
                onHover={onHover}
                onFocus={onFocus}
              />
            ))}
          </tbody>
        </table>
      </div>
      <p className="hint">Wind in mph (gusts), rain and snow in in/hr at the truck's ETA. Click a row to find it on the map.</p>
    </section>
  )
})
