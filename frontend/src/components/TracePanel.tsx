import type { Trace } from '../types'

/**
 * "Under the hood": what each layer of the pipeline did for this one answer.
 * Everything shown here is measured server-side for this request.
 */
export function TracePanel({ trace }: { trace: Trace }) {
  if (!trace || !trace.retrieval) return null
  const { query, retrieval, gate, graph, llm, verification, security } = trace
  const seconds = trace.total_ms != null ? `${(trace.total_ms / 1000).toFixed(1)} s` : ''

  const steps: { label: string; detail: string; tone?: 'ok' | 'warn' | 'skip' }[] = [
    {
      label: 'Query understanding',
      detail: query?.expanded
        ? `Added insurance terms: ${query.search_query.slice(query.search_query.indexOf('('))}`
        : 'No everyday-language terms to translate',
    },
    {
      label: 'Hybrid search',
      detail: `${retrieval.candidates} candidates from meaning + keyword search · ${retrieval.search_ms} ms`,
    },
    {
      label: 'Rerank',
      detail: `Cross-encoder scored every candidate, kept ${retrieval.policy_chunks} policy + ${retrieval.federal_chunks} federal sections · ${retrieval.rerank_ms} ms`,
    },
    {
      label: 'Relevance gate',
      detail: gate.passed
        ? `Passed (best score ${gate.best_score} ≥ ${gate.threshold})`
        : `Blocked (best score ${gate.best_score} < ${gate.threshold}), so no AI call was made`,
      tone: gate.passed ? 'ok' : 'skip',
    },
  ]
  if (gate.passed) {
    steps.push({
      label: 'Clause graph',
      detail: graph.linked_clauses.length
        ? `Followed cross-references to ${graph.linked_clauses.length} more clause(s): ${graph.linked_clauses
            .map((s) => s?.split('›').pop()?.trim())
            .join(', ')}`
        : 'No extra clauses needed (no cross-references, or they were already in the results)',
    })
  }
  if (llm) {
    steps.push({
      label: 'Language model',
      detail: `${llm.model ?? 'model'}${llm.fallbacks_used ? ` (fallback #${llm.fallbacks_used})` : ''}${
        llm.input_tokens ? ` · ${llm.input_tokens} in / ${llm.output_tokens} out tokens` : ''
      } · ${llm.ms} ms`,
    })
  }
  if (verification) {
    const notes = [
      `${verification.quotes_verified}/${verification.quotes_proposed} quotes verified against the policy text`,
      verification.contacts_removed ? `${verification.contacts_removed} unsupported contact(s) removed` : '',
      verification.markup_removed ? `${verification.markup_removed} HTML tag(s) removed` : '',
      verification.conflict_flagged ? 'conflicting clauses flagged' : '',
      verification.final_verdict !== verification.verdict_from_model
        ? `verdict changed ${verification.verdict_from_model} → ${verification.final_verdict}`
        : '',
    ].filter(Boolean)
    steps.push({
      label: 'Verification',
      detail: notes.join(' · '),
      tone: verification.quotes_verified === verification.quotes_proposed ? 'ok' : 'warn',
    })
  }
  if (security?.document_lines_removed) {
    steps.push({
      label: 'Injection scanner',
      detail: `${security.document_lines_removed} instruction-like line(s) were removed from this document before indexing`,
      tone: 'warn',
    })
  }

  return (
    <details className="trace">
      <summary>Under the hood{seconds && ` · ${seconds}`}</summary>
      <ol>
        {steps.map((s) => (
          <li key={s.label} className={s.tone ? `trace-${s.tone}` : undefined}>
            <strong>{s.label}</strong>
            <span>{s.detail}</span>
          </li>
        ))}
      </ol>
    </details>
  )
}
