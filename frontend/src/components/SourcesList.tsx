import { documentFileUrl } from '../api'
import { shortSection } from '../format'
import type { SourcePreview } from '../types'

/** Everything retrieval found - shown collapsed, for transparency about what the AI read. */
export function SourcesList({ sources, docId }: { sources: SourcePreview[]; docId: string }) {
  if (sources.length === 0) return null
  return (
    <details className="sources">
      <summary>
        What I read: {sources.length} section{sources.length === 1 ? '' : 's'}
      </summary>
      <ul>
        {sources.map((s) => (
          <li key={s.source_id}>
            <header>
              <span>
                {s.source_id} · {s.kind === 'policy' ? shortSection(s.section) ?? 'Your policy' : s.title}
              </span>
              {s.kind === 'policy' && s.page ? (
                <a href={documentFileUrl(docId, s.page)} target="_blank" rel="noreferrer">
                  p. {s.page}
                </a>
              ) : s.url ? (
                <a href={s.url} target="_blank" rel="noreferrer">
                  source
                </a>
              ) : null}
            </header>
            {s.linked_from && <small className="linked">Pulled in because {s.linked_from} cross-references it</small>}
            <p>{s.text}</p>
          </li>
        ))}
      </ul>
    </details>
  )
}
