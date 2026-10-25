// Mirrors backend/app/schemas.py. Keep the two in sync.

export type Verdict =
  | 'covered'
  | 'covered_with_conditions'
  | 'not_covered'
  | 'unclear'
  | 'not_in_policy'
  | 'informational'

export interface Citation {
  source_id: string
  quote: string
  page: number | null
  section: string | null
}

export interface FederalReference {
  source_id: string
  note: string
  title: string
  url: string | null
}

export interface CostEstimate {
  billed_amount: number
  you_pay: number
  plan_pays: number
  steps: string[]
  assumptions: string[]
}

export interface Answer {
  verdict: Verdict
  headline: string
  explanation: string
  citations: Citation[]
  conditions: string[]
  exclusions: string[]
  federal: FederalReference[]
  questions_to_ask: string[]
  cost_estimate: CostEstimate | null
  warnings: string[]
  used_llm: boolean
}

export interface SourcePreview {
  source_id: string
  kind: 'policy' | 'federal'
  page: number | null
  section: string | null
  title: string
  url: string | null
  text: string
  score: number
}

export interface PlanFacts {
  plan_name?: string | null
  insurer?: string | null
  plan_type?: string | null
  plan_year?: string | null
  deductible_individual?: number | null
  deductible_family?: number | null
  oop_max_individual?: number | null
  oop_max_family?: number | null
  coinsurance_in_network_percent?: number | null
  primary_care_copay?: number | null
  specialist_copay?: number | null
  emergency_room_copay?: number | null
}

export interface DocumentInfo {
  doc_id: string
  title: string
  filename: string
  pages: number
  chunks: number
  is_sample: boolean
  facts: PlanFacts | null
  created_at: string
}

export interface Health {
  status: string
  llm_configured: boolean
  llm_provider: 'gemini' | 'anthropic' | null
}
