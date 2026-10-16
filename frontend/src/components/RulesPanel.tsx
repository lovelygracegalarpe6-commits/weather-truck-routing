import { memo } from 'react'
import { RISK_META } from '../map/colors'

const ROWS = [
  ['Wind (mph)', '< 25', '25–34', '35–44', '45–54', '≥ 55'],
  ['Rain (in/hr)', '< 0.10', '0.10–0.25', '> 0.25–0.50', '> 0.50–1.00', '> 1.00'],
  ['Snow (in/hr)', '< 0.5', '0.5–1.0', '> 1.0–2.0', '> 2.0–3.0', '> 3.0'],
]

/** The rules the planner applies, so every number on screen can be checked. */
export const RulesPanel = memo(function RulesPanel({ truckMaxSpeedMph = 65 }: { truckMaxSpeedMph?: number }) {
  return (
    <details className="card rules">
      <summary>How risk is scored</summary>
      <table>
        <thead>
          <tr>
            <th scope="col" />
            {(['low', 'moderate', 'high', 'severe', 'no_travel'] as const).map((k) => (
              <th key={k} scope="col">
                <span className="swatch" style={{ background: RISK_META[k].color }} />
                {RISK_META[k].label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ROWS.map(([name, ...cells]) => (
            <tr key={name}>
              <th scope="row">{name}</th>
              {cells.map((c) => (
                <td key={c}>{c}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <ul>
        <li>Wind 45–54 mph with a load over 30,000 lb → No Travel.</li>
        <li>Wind 35–44 mph with a load over 40,000 lb → Severe.</li>
        <li>A checkpoint takes the worst of wind, rain and snow at the truck's ETA.</li>
        <li>
          Routes are ranked by fewest No Travel miles, then Severe miles, High miles, lowest average risk and
          finally shortest travel time.
        </li>
        <li>Travel time caps the truck at {truckMaxSpeedMph} mph on every road segment.</li>
      </ul>
    </details>
  )
})
