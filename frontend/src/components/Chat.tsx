import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from 'react'
import { ApiError, askQuestion } from '../api'
import type { Answer, DocumentInfo, SourcePreview } from '../types'
import { AnswerCard } from './AnswerCard'

interface Turn {
  id: number
  question: string
  state: 'loading' | 'done' | 'error'
  statusText: string
  sources: SourcePreview[]
  answer: Answer | null
  error: string | null
}

const SAMPLE_SUGGESTIONS = [
  'I broke my arm on vacation in Spain. Am I covered?',
  'My knee MRI costs $1,800 and I haven’t met my deductible. What will I pay?',
  'Is Wegovy covered for weight loss?',
  'Is adult dental care covered?',
  'Can the out-of-network anesthesiologist bill me extra?',
  'My claim was denied. How long do I have to appeal?',
]

const UPLOAD_SUGGESTIONS = [
  'What is my deductible and out-of-pocket maximum?',
  'Do I need prior authorization for an MRI?',
  'Is emergency care covered when I travel abroad?',
  'What does my plan exclude?',
]

let nextId = 1

export function Chat({ doc }: { doc: DocumentInfo | null }) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [input, setInput] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const endRef = useRef<HTMLDivElement>(null)
  const busy = turns.some((t) => t.state === 'loading')

  // a new document means a new conversation
  useEffect(() => {
    abortRef.current?.abort()
    setTurns([])
  }, [doc?.doc_id])

  useEffect(() => () => abortRef.current?.abort(), [])

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns])

  function update(id: number, patch: Partial<Turn>) {
    setTurns((all) => all.map((t) => (t.id === id ? { ...t, ...patch } : t)))
  }

  async function run(id: number, question: string) {
    if (!doc) return
    const controller = new AbortController()
    abortRef.current = controller
    let finished = false
    try {
      await askQuestion(
        question,
        doc.doc_id,
        {
          onStatus: (statusText) => update(id, { statusText }),
          onSources: (sources) => update(id, { sources }),
          onAnswer: (answer) => {
            finished = true
            update(id, { answer, state: 'done' })
          },
          onError: (error) => {
            finished = true
            update(id, { error, state: 'error' })
          },
        },
        controller.signal,
      )
      if (!finished) update(id, { state: 'error', error: 'The connection closed before the answer arrived.' })
    } catch (e) {
      if (controller.signal.aborted) return
      const message = e instanceof ApiError ? e.message : 'Couldn’t reach the server. Check your connection and try again.'
      update(id, { state: 'error', error: message })
    }
  }

  function ask(question: string) {
    const q = question.trim()
    if (!q || busy || !doc) return
    const id = nextId++
    setTurns((all) => [
      ...all,
      { id, question: q, state: 'loading', statusText: 'Sending…', sources: [], answer: null, error: null },
    ])
    setInput('')
    run(id, q)
  }

  function retry(turn: Turn) {
    update(turn.id, { state: 'loading', statusText: 'Retrying…', error: null, sources: [] })
    run(turn.id, turn.question)
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    ask(input)
  }

  function onKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      ask(input)
    }
  }

  const suggestions = doc?.is_sample === false ? UPLOAD_SUGGESTIONS : SAMPLE_SUGGESTIONS

  return (
    <main className="card chat">
      <div className="messages" aria-live="polite">
        {turns.length === 0 && (
          <div className="empty">
            <h2>What do you want to know about your coverage?</h2>
            <p>
              Ask in plain English. Every answer quotes the exact clause and page from the policy, adds the federal
              rules that protect you, and tells you what to ask your insurer.
            </p>
            <div className="suggestions">
              {suggestions.map((s) => (
                <button key={s} type="button" className="chip" onClick={() => ask(s)} disabled={!doc}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn) => (
          <div key={turn.id} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div className="user-msg">{turn.question}</div>

            {turn.state === 'loading' && (
              <div className="card thinking" role="status">
                <span className="status">
                  <span className="spinner" aria-hidden="true" />
                  {turn.statusText}
                  {turn.sources.length > 0 && ` Found ${turn.sources.length} relevant sections.`}
                </span>
                <div className="skeleton" style={{ width: '70%' }} />
                <div className="skeleton" style={{ width: '90%' }} />
                <div className="skeleton" style={{ width: '55%' }} />
              </div>
            )}

            {turn.state === 'error' && (
              <div className="error" role="alert">
                <span>{turn.error}</span>
                <button type="button" className="button secondary" onClick={() => retry(turn)} disabled={busy}>
                  Try again
                </button>
              </div>
            )}

            {turn.state === 'done' && turn.answer && doc && (
              <AnswerCard answer={turn.answer} sources={turn.sources} docId={doc.doc_id} />
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={onSubmit}>
        <label htmlFor="question" className="visually-hidden">
          Your question
        </label>
        <textarea
          id="question"
          rows={1}
          maxLength={500}
          placeholder={doc ? 'e.g. Is physical therapy covered?' : 'Loading policy…'}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={onKeyDown}
          disabled={!doc}
        />
        <button className="button" type="submit" disabled={busy || !doc || input.trim().length < 3}>
          {busy ? 'Thinking…' : 'Ask'}
        </button>
      </form>
    </main>
  )
}
