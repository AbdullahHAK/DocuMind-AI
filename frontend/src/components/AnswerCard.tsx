import { documentFileUrl } from '../api'
import { shortSection } from '../format'
import type { Answer, SourcePreview } from '../types'
import { CostBreakdown } from './CostBreakdown'
import { SourcesList } from './SourcesList'
import { TracePanel } from './TracePanel'
import { VerdictBadge } from './VerdictBadge'

interface Props {
  answer: Answer
  sources: SourcePreview[]
  docId: string
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null
  return (
    <div>
      <p className="section-title">{title}</p>
      <ul className="list">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  )
}

export function AnswerCard({ answer, sources, docId }: Props) {
  return (
    <article className="card answer" aria-label="Answer">
      <VerdictBadge verdict={answer.verdict} />
      <h3 className="headline">{answer.headline}</h3>
      <p className="explanation">{answer.explanation}</p>

      {answer.warnings.map((w) => (
        <div className="warning" role="note" key={w}>
          {w}
        </div>
      ))}

      {answer.cost_estimate && <CostBreakdown estimate={answer.cost_estimate} />}

      {(answer.conditions.length > 0 || answer.exclusions.length > 0) && (
        <div className="two-col">
          <List title="Conditions" items={answer.conditions} />
          <List title="Not covered" items={answer.exclusions} />
        </div>
      )}

      {answer.citations.length > 0 && (
        <section>
          <p className="section-title">What your policy says</p>
          {answer.citations.map((c) => (
            <figure className="quote" key={`${c.source_id}-${c.quote}`}>
              <blockquote>“{c.quote}”</blockquote>
              <figcaption>
                <a href={documentFileUrl(docId, c.page)} target="_blank" rel="noreferrer">
                  {c.page ? `Page ${c.page}` : 'Your policy'}
                  {c.section ? ` · ${shortSection(c.section)}` : ''} ↗
                </a>
              </figcaption>
            </figure>
          ))}
        </section>
      )}

      {answer.federal.length > 0 && (
        <section className="federal">
          <p className="section-title">What federal law says</p>
          {answer.federal.map((f) => (
            <p key={f.source_id}>
              {f.note}
              <small>
                {f.url ? (
                  <a href={f.url} target="_blank" rel="noreferrer">
                    {f.title} ↗
                  </a>
                ) : (
                  f.title
                )}
              </small>
            </p>
          ))}
        </section>
      )}

      <List title="Ask your insurer" items={answer.questions_to_ask} />
      <SourcesList sources={sources} docId={docId} />
      <TracePanel trace={answer.trace} />
    </article>
  )
}
