import { memo } from 'react'
import type { PlanResponse } from '../api/types'
import { formatDateTime, formatDateTimeLong, formatDuration, formatMiles, formatPounds } from '../lib/format'
import { Icon } from './Icon'
import { RiskChip } from './RiskChip'
import { RiskProfile } from './RiskProfile'

export const Recommendation = memo(function Recommendation({ plan }: { plan: PlanResponse }) {
  const { trip, recommendation } = plan
  const best = plan.routes.find((r) => r.id === recommendation.route_id)
  if (!best) return null
  const nameOf = (id: string) => plan.routes.find((r) => r.id === id)?.name ?? id
  const { miles_by_level: miles } = best.stats

  return (
    <section className="card recommendation" aria-labelledby="rec-title">
      <div className="rec-head">
        <span className="rec-badge" aria-hidden="true">
          {best.id}
        </span>
        <div>
          <p className="eyebrow">
            <Icon name="shield" size={13} /> Safest route
          </p>
          <h2 id="rec-title">{best.summary ? `via ${best.summary}` : best.name}</h2>
        </div>
      </div>

      <dl className="stat-tiles">
        <div>
          <dt>Drive time</dt>
          <dd>{formatDuration(best.duration_s)}</dd>
        </div>
        <div>
          <dt>Distance</dt>
          <dd>{formatMiles(best.distance_mi)}</dd>
        </div>
        <div>
          <dt>Arrive</dt>
          <dd>{formatDateTime(best.arrival_utc, trip.timezone)}</dd>
        </div>
        <div>
          <dt>Severe / High</dt>
          <dd>
            {formatMiles(miles.severe + miles.no_travel)} / {formatMiles(miles.high)}
          </dd>
        </div>
      </dl>

      <RiskProfile route={best} />
      <p className="rec-meta">
        <span>
          <Icon name="calendar" size={13} /> Departs {formatDateTimeLong(trip.departure_utc, trip.timezone)}
        </span>
        <span>
          <Icon name="weight" size={13} /> {formatPounds(trip.load_weight_lb)}
        </span>
        <RiskChip level={best.stats.max_level} compact />
      </p>

      {recommendation.warnings.map((w) => (
        <p key={w} className="warning" role="alert">
          <Icon name="alert" size={15} /> {w}
        </p>
      ))}
      {recommendation.comparisons.length > 0 && (
        <ul className="reasons">
          {recommendation.comparisons.map((c) => (
            <li key={c.other_route_id}>
              <Icon name="check" size={15} />
              <span>
                <strong>vs {nameOf(c.other_route_id)}.</strong> {c.text}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
})
