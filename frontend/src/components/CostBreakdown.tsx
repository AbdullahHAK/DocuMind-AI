import type { CostEstimate } from '../types'
import { formatMoney as money } from '../format'

/** The estimate is computed by the backend in plain Python - the LLM never does the math. */
export function CostBreakdown({ estimate }: { estimate: CostEstimate }) {
  return (
    <section className="cost" aria-label="Cost estimate">
      <p className="section-title">Estimated cost</p>
      <div className="cost-totals">
        <div>
          <span>You pay</span>
          <strong>{money(estimate.you_pay)}</strong>
        </div>
        <div>
          <span>Plan pays</span>
          <strong>{money(estimate.plan_pays)}</strong>
        </div>
        <div>
          <span>Bill</span>
          <strong>{money(estimate.billed_amount)}</strong>
        </div>
      </div>
      <ol>
        {estimate.steps.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>
      <small>Assumes: {estimate.assumptions.join(' ')}</small>
    </section>
  )
}
