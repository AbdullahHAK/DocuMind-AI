/** $1,800 for whole dollars, $1,234.56 otherwise. */
export function formatMoney(value: number | null | undefined): string {
  if (value == null) return '—'
  const whole = Number.isInteger(value)
  return value.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: whole ? 0 : 2,
    maximumFractionDigits: 2,
  })
}

/** "SECTION 7 - EXCLUSIONS › 7.3 Dental and Vision" -> "7.3 Dental and Vision" */
export function shortSection(section: string | null | undefined): string | null {
  if (!section) return null
  const parts = section.split('›')
  return parts[parts.length - 1].trim()
}
