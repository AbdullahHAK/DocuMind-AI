import { useCallback, useEffect, useState } from 'react'
import { fetchDocument, fetchHealth, SAMPLE_DOC_ID } from './api'
import { Chat } from './components/Chat'
import { DocumentPanel } from './components/DocumentPanel'
import type { DocumentInfo, Health } from './types'

const STORAGE_KEY = 'amicovered:doc'

function readSavedDocId(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY)
  } catch {
    return null // storage can be blocked (private mode, strict settings)
  }
}

function saveDocId(docId: string) {
  try {
    localStorage.setItem(STORAGE_KEY, docId)
  } catch {
    // non-essential: the app works without remembering the upload
  }
}

export default function App() {
  const [doc, setDoc] = useState<DocumentInfo | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [llmReady, setLlmReady] = useState(true)
  const [llmProvider, setLlmProvider] = useState<Health['llm_provider']>(null)

  const load = useCallback(async (docId: string) => {
    try {
      setLoadError(null)
      const info = await fetchDocument(docId)
      setDoc(info)
      saveDocId(info.doc_id)
    } catch {
      if (docId !== SAMPLE_DOC_ID) return load(SAMPLE_DOC_ID) // upload expired -> fall back to the sample
      setLoadError('Couldn’t load the policy. Is the server running?')
    }
  }, [])

  useEffect(() => {
    load(readSavedDocId() ?? SAMPLE_DOC_ID)
    fetchHealth()
      .then((h) => {
        setLlmReady(h.llm_configured)
        setLlmProvider(h.llm_provider)
      })
      .catch(() => setLlmReady(false))
  }, [load])

  return (
    <div className="app">
      <header className="header">
        <div className="brand">
          <div className="brand-mark" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 32 32">
              <path d="M16 5l9 3.4v6.8c0 5.6-3.8 10.4-9 12.3-5.2-1.9-9-6.7-9-12.3V8.4z" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" />
              <path d="M11.5 16l3 3 6-6.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </div>
          <div>
            <h1>Am I Covered?</h1>
            <p>Plain-English answers from your US health insurance policy</p>
          </div>
        </div>
        <span className="header-badge">Every answer cites the exact clause</span>
      </header>

      {!llmReady && (
        <div className="warning" role="status" style={{ marginBottom: 16 }}>
          The AI service isn’t configured on this server, so questions will show the policy sections found but no
          written answer.
        </div>
      )}

      <div className="layout">
        <DocumentPanel
          doc={doc}
          loadError={loadError}
          llmProvider={llmProvider}
          onUploaded={(uploaded) => {
            setDoc(uploaded)
            saveDocId(uploaded.doc_id)
          }}
          onUseSample={() => load(SAMPLE_DOC_ID)}
        />
        <Chat doc={doc} />
      </div>

      <footer className="footer">
        Built with retrieval-augmented generation: hybrid search, reranking, verified citations. Not legal or medical
        advice.
      </footer>
    </div>
  )
}
