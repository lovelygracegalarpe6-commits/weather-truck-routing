import type { RiskKey } from '../api/types'
import { riskColor, riskLabel, RISK_META } from '../map/colors'

export function RiskChip({ level, compact = false }: { level: RiskKey | null; compact?: boolean }) {
  return (
    <span
      className={compact ? 'risk-chip compact' : 'risk-chip'}
      style={{ background: riskColor(level), color: level ? RISK_META[level].ink : '#fff' }}
    >
      {riskLabel(level)}
    </span>
  )
}
