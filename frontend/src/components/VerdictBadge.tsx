import type { Verdict } from '../types'

const LABELS: Record<Verdict, string> = {
  covered: 'Covered',
  covered_with_conditions: 'Covered, with conditions',
  not_covered: 'Not covered',
  unclear: 'Unclear',
  not_in_policy: 'Not found in policy',
  informational: 'Policy info',
}

const ICONS: Record<Verdict, string> = {
  covered: '✓',
  covered_with_conditions: '!',
  not_covered: '✕',
  unclear: '?',
  not_in_policy: '?',
  informational: 'i',
}

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
  return (
    <span className={`verdict verdict-${verdict}`}>
      <span aria-hidden="true">{ICONS[verdict]}</span>
      {LABELS[verdict]}
    </span>
  )
}
