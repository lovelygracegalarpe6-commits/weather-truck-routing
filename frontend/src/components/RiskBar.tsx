import type { RouteStats } from '../api/types'
import { formatMiles } from '../lib/format'
import { RISK_KEYS, RISK_META, UNKNOWN_COLOR } from '../map/colors'

/** Stacked bar of miles by risk level. */
export function RiskBar({ stats }: { stats: RouteStats }) {
  const segments = [
    ...RISK_KEYS.map((key) => ({
      key,
      miles: stats.miles_by_level[key],
      color: RISK_META[key].color,
      label: RISK_META[key].label,
    })),
    { key: 'unknown', miles: stats.unknown_miles, color: UNKNOWN_COLOR, label: 'No forecast' },
  ].filter((s) => s.miles > 0)
  const total = segments.reduce((sum, s) => sum + s.miles, 0) || 1
  const description = segments.map((s) => `${s.label} ${formatMiles(s.miles)}`).join(', ')

  return (
    <div className="risk-bar" role="img" aria-label={`Miles by risk: ${description}`}>
      {segments.map((s) => (
        <span
          key={s.key}
          style={{ width: `${(s.miles / total) * 100}%`, background: s.color }}
          title={`${s.label}: ${formatMiles(s.miles)}`}
        />
      ))}
    </div>
  )
}
