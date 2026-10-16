import { memo } from 'react'
import type { Route } from '../api/types'
import { formatMiles } from '../lib/format'
import { riskColor, riskLabel } from '../map/colors'

/**
 * Risk along the route, in order: one segment per checkpoint, as wide as the road it
 * represents and coloured by its level, so you can see *where* the weather bites.
 */
export const RiskProfile = memo(function RiskProfile({ route }: { route: Route }) {
  const { checkpoints, stats } = route
  // Thin separators read well for a few dozen checkpoints but turn to noise beyond that.
  const dense = checkpoints.length > 60
  const summary = Object.entries(stats.miles_by_level)
    .filter(([, miles]) => miles > 0)
    .map(([level, miles]) => `${riskLabel(level as Route['stats']['max_level'])} ${formatMiles(miles)}`)
    .join(', ')

  return (
    <div className={dense ? 'risk-profile dense' : 'risk-profile'} role="img" aria-label={`Risk along Route ${route.id}: ${summary}`}>
      {checkpoints.map((cp) => (
        <span
          key={cp.index}
          style={{ flexGrow: Math.max(cp.represents_miles, 0.1), background: riskColor(cp.level) }}
          title={`Mile ${Math.round(cp.mile)} · ${riskLabel(cp.level)}`}
        />
      ))}
    </div>
  )
})
