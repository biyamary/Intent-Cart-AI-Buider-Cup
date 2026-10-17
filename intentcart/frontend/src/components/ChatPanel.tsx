import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { post } from '../lib/api'
import { ErrorMessage } from './Feedback'

export function ChatPanel({ scanId }: { scanId: string }) {
  const [question, setQuestion] = useState('')
  const ask = useMutation({
    mutationFn: () =>
      post<{ answer: string; sources: string[] }>(`/food/scans/${scanId}/ask`, { question }),
  })
  return (
    <section className="panel stack">
      <h3>A question about this label?</h3>
      <form
        className="stack"
        onSubmit={(e) => {
          e.preventDefault()
          ask.mutate()
        }}
      >
        <label>
          Follow-up question
          <input
            required
            maxLength={2000}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask about a finding in your report"
          />
        </label>
        <button className="secondary" disabled={ask.isPending || !question.trim()}>
          {ask.isPending ? 'Thinking…' : 'Ask assistant'}
        </button>
      </form>
      <ErrorMessage error={ask.error} />
      {ask.data && (
        <div className="notice" aria-live="polite">
          <p>{ask.data.answer}</p>
          {ask.data.sources.map((url) => (
            <a key={url} href={url} target="_blank" rel="noreferrer">
              View source
            </a>
          ))}
        </div>
      )}
    </section>
  )
}
