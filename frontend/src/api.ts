import type { Answer, DocumentInfo, Health, SourcePreview } from './types'

export const SAMPLE_DOC_ID = 'sample-evergreen'

export class ApiError extends Error {}

async function errorMessage(res: Response): Promise<string> {
  try {
    const body = await res.json()
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) return 'Please check your question and try again.'
  } catch {
    // not JSON - fall through
  }
  return `Request failed (${res.status}). Please try again.`
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new ApiError(await errorMessage(res))
  return res.json()
}

export const fetchHealth = () => getJson<Health>('/api/health')
export const fetchDocument = (docId: string) => getJson<DocumentInfo>(`/api/documents/${encodeURIComponent(docId)}`)
export const documentFileUrl = (docId: string, page?: number | null) =>
  `/api/documents/${encodeURIComponent(docId)}/file${page ? `#page=${page}` : ''}`

export async function uploadDocument(file: File): Promise<DocumentInfo> {
  const form = new FormData()
  form.append('file', file)
  const res = await fetch('/api/documents', { method: 'POST', body: form })
  if (!res.ok) throw new ApiError(await errorMessage(res))
  return res.json()
}

export interface AskHandlers {
  onStatus: (message: string) => void
  onSources: (sources: SourcePreview[]) => void
  onAnswer: (answer: Answer) => void
  onError: (message: string) => void
}

/**
 * POST a question and consume the Server-Sent Events stream.
 *
 * The browser's EventSource only supports GET, so we read the response body
 * ourselves: SSE is just text where events are separated by a blank line and
 * each event has "event: <name>" and "data: <json>" lines.
 */
export async function askQuestion(question: string, docId: string, handlers: AskHandlers, signal?: AbortSignal) {
  const res = await fetch('/api/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, doc_id: docId }),
    signal,
  })
  if (!res.ok || !res.body) throw new ApiError(await errorMessage(res))

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    let boundary: number
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, boundary)
      buffer = buffer.slice(boundary + 2)
      dispatch(raw, handlers)
    }
  }
}

function dispatch(raw: string, handlers: AskHandlers) {
  let event = 'message'
  let data = ''
  for (const line of raw.split('\n')) {
    if (line.startsWith('event: ')) event = line.slice(7)
    else if (line.startsWith('data: ')) data += line.slice(6)
  }
  const payload = data ? JSON.parse(data) : null
  switch (event) {
    case 'status':
      handlers.onStatus(payload.message)
      break
    case 'sources':
      handlers.onSources(payload)
      break
    case 'answer':
      handlers.onAnswer(payload)
      break
    case 'error':
      handlers.onError(payload.message)
      break
  }
}
