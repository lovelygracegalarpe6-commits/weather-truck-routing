import { memo } from 'react'
import type { PlanResponse } from '../api/types'
import { formatDateTimeLong, formatDuration, formatPounds } from '../lib/format'

export const Recommendation = memo(function Recommendation({ plan }: { plan: PlanResponse }) {
  const { trip, recommendation } = plan
  const best = plan.routes.find((r) => r.id === recommendation.route_id)
  if (!best) return null
  const nameOf = (id: string) => plan.routes.find((r) => r.id === id)?.name ?? id

  return (
    <section className="card recommendation" aria-labelledby="rec-title">
      <p className="eyebrow">Recommended</p>
      <h2 id="rec-title">
        <span className="route-badge">{best.id}</span>
        {best.summary ? `via ${best.summary}` : best.name}
      </h2>
      <p className="muted">
        {formatDuration(best.duration_s)} · departs {formatDateTimeLong(trip.departure_utc, trip.timezone)} ·{' '}
        {formatPounds(trip.load_weight_lb)}
      </p>
      {recommendation.warnings.map((w) => (
        <p key={w} className="warning" role="alert">
          {w}
        </p>
      ))}
      {recommendation.comparisons.length > 0 && (
        <ul className="reasons">
          {recommendation.comparisons.map((c) => (
            <li key={c.other_route_id}>
              <strong>vs {nameOf(c.other_route_id)}:</strong> {c.text}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
})
