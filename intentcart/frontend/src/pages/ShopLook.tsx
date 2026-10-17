import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUp, MessageSquare, Plus, Search, Sparkles } from 'lucide-react'
import { api, post } from '../lib/api'
import type { AgentInfo, Conversation, ConversationSummary } from '../lib/conversations'
import { AgentMessage } from '../components/AgentMessage'
import { ErrorMessage, PageTitle } from '../components/Feedback'

const sessionPath = '/agents/stylist/sessions'
const starters = [
  "I want an outfit for my sister's mehendi.",
  'Help me find a relaxed outfit for a beach wedding.',
  'I need a smart casual look for a work dinner under ₹5,000.',
]

export function ShopLook() {
  const cache = useQueryClient()
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('chat')
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const agents = useQuery({ queryKey: ['agents'], queryFn: () => api<AgentInfo[]>('/agents') })
  const stylist = agents.data?.find((agent) => agent.id === 'stylist')
  const enabled = stylist?.enabled ?? false
  const searchEnabled = stylist?.capabilities?.includes('google_search') ?? false
  const history = useQuery({
    queryKey: ['stylist-sessions'],
    queryFn: () => api<ConversationSummary[]>(sessionPath),
  })
  const send = useMutation({
    retry: false,
    mutationFn: async (body: { text: string; request_id: string }) => {
      let id = sessionId
      if (!id) {
        const created = await post<Conversation>(sessionPath)
        id = created.id
        cache.setQueryData(['stylist-session', id], created)
        setParams({ chat: id })
      }
      try {
        const conversation = await post<Conversation>(`${sessionPath}/${id}/messages`, body)
        cache.setQueryData(['stylist-session', id], conversation)
        return conversation
      } finally {
        void cache.invalidateQueries({ queryKey: ['stylist-session', id] })
        void cache.invalidateQueries({ queryKey: ['stylist-sessions'] })
      }
    },
  })
  const conversation = useQuery({
    queryKey: ['stylist-session', sessionId],
    queryFn: () => api<Conversation>(`${sessionPath}/${sessionId}`),
    enabled: Boolean(sessionId) && !send.isPending,
    staleTime: 30_000,
    retry: false,
  })
  const messages = conversation.data?.messages ?? []
  const pendingText = send.isPending ? send.variables.text : null
  const busy = send.isPending || (Boolean(sessionId) && conversation.isPending)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
  }, [messages.length, send.isPending])
  function submit() {
    const text = draft.trim()
    if (!text || busy || !enabled || conversation.isError) return
    send.mutate({ text, request_id: crypto.randomUUID() })
    setDraft('')
  }
  function selectConversation(id?: string) {
    setParams(id ? { chat: id } : {})
    setDraft('')
    send.reset()
  }
  return (
    <>
      <PageTitle
        eyebrow="SHOP A LOOK"
        title="Let's find your kind of look."
        description="Start with an occasion, a thought, or a style you love. Your stylist will help shape the rest."
      />
      <div className="style-chat-layout">
        <section className="panel conversation-panel" aria-label="Shop a look conversation">
          <div className="conversation-heading">
            <div>
              <span className="stylist-avatar">
                <Sparkles size={18} />
              </span>
              <div>
                <h2>Your personal stylist</h2>
                <span className="muted">A conversation, then a plan</span>
              </div>
            </div>
            {searchEnabled && (
              <span className="search-capability">
                <Search size={13} /> Google Search
              </span>
            )}
          </div>
          <ErrorMessage error={agents.error || conversation.error} />
          {agents.isSuccess && !enabled && (
            <div className="notice">
              Live chat is not enabled in this environment. You can still explore the{' '}
              <Link className="text-link" to="/clothes/board">
                sample look board ↗
              </Link>
              .
            </div>
          )}
          <div
            className="conversation-messages"
            role="log"
            aria-label="Conversation messages"
            aria-live="polite"
          >
            {!sessionId && !pendingText && (
              <div className="conversation-welcome">
                <div className="welcome-spark">
                  <Sparkles size={29} strokeWidth={1.3} />
                </div>
                <h3>What are you dressing for?</h3>
                <p>
                  Tell me a little about the occasion. We'll work out your style, budget, and the
                  pieces together.
                </p>
                <div className="conversation-starters">
                  {starters.map((text) => (
                    <button
                      className="secondary"
                      key={text}
                      disabled={busy}
                      onClick={() => {
                        setDraft(text)
                        composer.current?.focus()
                      }}
                    >
                      {text}
                      <span aria-hidden="true">↗</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            {sessionId && conversation.isPending && !send.isPending && (
              <p className="chat-loading">Loading your conversation…</p>
            )}
            {sessionId && conversation.isSuccess && !messages.length && !pendingText && (
              <p className="chat-loading">Tell your stylist about the occasion to get started.</p>
            )}
            {messages.map((message) => (
              <AgentMessage key={message.id} message={message} />
            ))}
            {pendingText && (
              <>
                <article className="chat-message from-user">
                  <div className="message-author">
                    <strong>You</strong>
                  </div>
                  <p className="user-message-text">{pendingText}</p>
                </article>
                <div className="agent-working" role="status">
                  <span className="working-dot" /> Your stylist is working on a reply…
                </div>
              </>
            )}
            <div ref={end} />
          </div>
          <ErrorMessage error={send.error} />
          <form
            className="chat-composer"
            onSubmit={(e) => {
              e.preventDefault()
              submit()
            }}
          >
            <label className="sr-only" htmlFor="style-message">
              Message your stylist
            </label>
            <textarea
              id="style-message"
              ref={composer}
              rows={2}
              maxLength={4000}
              disabled={busy || !enabled}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="I want an outfit for my sister's mehendi…"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
            <button
              aria-label="Send message"
              disabled={busy || !enabled || !draft.trim() || conversation.isError}
            >
              <ArrowUp size={21} />
            </button>
          </form>
          <p className="fine-print chat-footer-note">
            {searchEnabled
              ? 'Text conversations for now. Search results may change; check prices and availability with the retailer.'
              : 'Style ideas and outfit planning. Live product search is currently unavailable.'}
          </p>
        </section>
        <aside className="stack conversation-sidebar">
          <button
            className="secondary"
            disabled={send.isPending}
            onClick={() => selectConversation()}
          >
            <Plus size={16} /> Start a new look
          </button>
          <section className="panel tinted">
            <span className="eyebrow">A LITTLE DIRECTION</span>
            <h3>
              Your occasion.
              <br />
              Your preferences.
            </h3>
            <p>
              Share your budget, outfit preferences, and shopping country.{' '}
              {searchEnabled
                ? 'Your stylist can look for current options once the brief is clear.'
                : 'Your stylist will help coordinate outfits and plan your budget.'}
            </p>
            <Link className="text-link" to="/profile">
              Edit style preferences ↗
            </Link>
          </section>
          <section className="panel">
            <h3>
              <MessageSquare size={16} /> Recent conversations
            </h3>
            <ErrorMessage error={history.error} />
            {history.isPending && <p>Loading conversations…</p>}
            {history.data?.length ? (
              <div className="history-list">
                {history.data.map((item) => (
                  <button
                    key={item.id}
                    className={`history-item ${sessionId === item.id ? 'current-conversation' : ''}`}
                    disabled={send.isPending}
                    onClick={() => selectConversation(item.id)}
                  >
                    <strong>{item.title}</strong>
                    <span>
                      {new Date(item.updated_at * 1000).toLocaleDateString()} · Continue ↗
                    </span>
                  </button>
                ))}
              </div>
            ) : (
              history.isSuccess && <p>Your conversations will appear here.</p>
            )}
          </section>
          <Link className="text-link sample-board-link" to="/clothes/board">
            Explore the sample look board ↗
          </Link>
        </aside>
      </div>
    </>
  )
}
