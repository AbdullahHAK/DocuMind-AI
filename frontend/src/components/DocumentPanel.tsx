import { useRef, useState } from 'react'
import { documentFileUrl, uploadDocument } from '../api'
import { formatMoney as money } from '../format'
import type { DocumentInfo, PlanFacts } from '../types'

interface Props {
  doc: DocumentInfo | null
  loadError: string | null
  onUploaded: (doc: DocumentInfo) => void
  onUseSample: () => void
}


const FACTS: { key: keyof PlanFacts; label: string; format?: (n: number) => string }[] = [
  { key: 'deductible_individual', label: 'Deductible' },
  { key: 'oop_max_individual', label: 'Out-of-pocket max' },
  { key: 'coinsurance_in_network_percent', label: 'Coinsurance', format: (n) => `${n}%` },
  { key: 'primary_care_copay', label: 'Primary care visit' },
  { key: 'specialist_copay', label: 'Specialist visit' },
  { key: 'emergency_room_copay', label: 'Emergency room' },
]

function FactsGrid({ facts }: { facts: PlanFacts }) {
  const shown = FACTS.filter((f) => facts[f.key] != null)
  if (shown.length === 0) return null
  return (
    <dl className="facts">
      {shown.map((f) => {
        const value = facts[f.key] as number
        return (
          <div className="fact" key={f.key}>
            <dt>{f.label}</dt>
            <dd>{f.format ? f.format(value) : money(value)}</dd>
          </div>
        )
      })}
    </dl>
  )
}

export function DocumentPanel({ doc, loadError, onUploaded, onUseSample }: Props) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [dragging, setDragging] = useState(false)

  async function handleFile(file: File | undefined) {
    if (!file) return
    if (file.type && file.type !== 'application/pdf') {
      setError('Please choose a PDF file.')
      return
    }
    setError(null)
    setUploading(true)
    try {
      onUploaded(await uploadDocument(file))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed. Please try again.')
    } finally {
      setUploading(false)
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  return (
    <aside className="sidebar">
      <section className="card doc-card" aria-label="Current policy">
        <p className="eyebrow">{doc?.is_sample ? 'Sample policy' : 'Your policy'}</p>
        {doc ? (
          <>
            <p className="doc-title">{doc.title}</p>
            <p className="doc-meta">
              {doc.pages} pages ·{' '}
              <a href={documentFileUrl(doc.doc_id)} target="_blank" rel="noreferrer">
                open PDF ↗
              </a>
            </p>
            {doc.facts && <FactsGrid facts={doc.facts} />}
            {!doc.is_sample && (
              <button className="link-button" type="button" onClick={onUseSample}>
                Switch back to the sample policy
              </button>
            )}
          </>
        ) : (
          <p className="doc-meta">{loadError ?? 'Loading…'}</p>
        )}
      </section>

      <label
        className={`dropzone${dragging ? ' dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          handleFile(e.dataTransfer.files[0])
        }}
      >
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf"
          className="visually-hidden"
          disabled={uploading}
          onChange={(e) => handleFile(e.target.files?.[0])}
        />
        {uploading ? (
          <span className="status" style={{ justifyContent: 'center' }}>
            <span className="spinner" aria-hidden="true" /> Reading and indexing your policy…
          </span>
        ) : (
          <>
            <strong>Upload your own policy</strong>
            <span>Drop your plan's PDF (Summary of Benefits or Evidence of Coverage), max 10 MB</span>
          </>
        )}
      </label>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      <p className="note">
        Uploaded files are deleted automatically after 24 hours. Answers are for understanding your coverage, not legal or
        medical advice. Always confirm with your insurer.
      </p>
    </aside>
  )
}
