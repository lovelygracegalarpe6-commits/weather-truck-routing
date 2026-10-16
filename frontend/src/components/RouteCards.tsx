import { memo } from 'react'
import type { PlanResponse } from '../api/types'
import { formatDateTime, formatDuration, formatMiles } from '../lib/format'
import { Icon } from './Icon'
import { RiskChip } from './RiskChip'
import { RiskProfile } from './RiskProfile'

interface Props {
  plan: PlanResponse
  selectedId: string | null
  onSelect: (id: string) => void
}

export const RouteCards = memo(function RouteCards({ plan, selectedId, onSelect }: Props) {
  const routes = [...plan.routes].sort((a, b) => a.rank - b.rank)
  const tz = plan.trip.timezone

  return (
    <section aria-labelledby="routes-title" className="route-cards">
      <h3 id="routes-title" className="section-title">
        All routes <span>ranked by weather risk, then time</span>
      </h3>
      {routes.map((route) => {
        const { stats } = route
        const selected = route.id === selectedId
        return (
          <button
            key={route.id}
            type="button"
            className={`card route-card${selected ? ' selected' : ''}`}
            aria-pressed={selected}
            onClick={() => onSelect(route.id)}
          >
            <div className="route-card-head">
              <span className="route-badge">{route.id}</span>
              <span className="route-title">{route.summary ? `via ${route.summary}` : route.name}</span>
              {route.recommended ? <span className="tag">Safest</span> : <span className="rank">#{route.rank}</span>}
            </div>
            <div className="route-metrics">
              <span>
                <Icon name="clock" size={13} /> <strong>{formatDuration(route.duration_s)}</strong>
              </span>
              <span>
                <Icon name="route" size={13} /> {formatMiles(route.distance_mi)}
              </span>
              <span>
                <Icon name="flag" size={13} /> {formatDateTime(route.arrival_utc, tz)}
              </span>
            </div>
            <RiskProfile route={route} />
            <div className="route-risk">
              <span>
                Severe <strong>{formatMiles(stats.miles_by_level.severe)}</strong>
              </span>
              <span>
                High <strong>{formatMiles(stats.miles_by_level.high)}</strong>
              </span>
              <span>
                Avg <strong>{stats.average_risk === null ? '—' : stats.average_risk.toFixed(2)}</strong>
              </span>
              {stats.miles_by_level.no_travel > 0 && (
                <span className="danger">
                  No travel <strong>{formatMiles(stats.miles_by_level.no_travel)}</strong>
                </span>
              )}
              <RiskChip level={stats.max_level} compact />
            </div>
          </button>
        )
      })}
    </section>
  )
})
