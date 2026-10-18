import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUp, Globe, MessageSquare, ScanLine, Search, Sparkles, Utensils } from 'lucide-react'
import { api, post } from '../lib/api'
import { useAgentTurn } from '../lib/agentTurns'
import { agents as agentProfiles } from '../lib/agents'
import type { AgentInfo, Conversation, ConversationSummary } from '../lib/conversations'
import { AgentMessage } from './AgentMessage'
import { AgentPageHeader } from './AgentPageHeader'
import { AgentProgress } from './AgentProgress'
import { ErrorMessage } from './Feedback'
import { SessionRail } from './SessionRail'

const sessionPath = '/agents/food/sessions'
const foodPresentation = agentProfiles.food
const starters = [
  'Can you review the ingredients of my snack bar?',
  'What is E171 and why is it banned in Europe?',
  'Check this cereal for my 4-year-old: whole grain wheat, sugar, malt extract, BHT.',
]
const foodProgress = [
  { id: 'queued', label: 'Waiting to start' },
  { id: 'understanding', label: 'Understanding your request' },
  { id: 'researching', label: 'Checking trusted food sources' },
  { id: 'preparing', label: 'Preparing your answer' },
]

export function FoodChat({ onSwitchToScanner }: { onSwitchToScanner?: () => void }) {
  const cache = useQueryClient()
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('food_chat')
  const [draft, setDraft] = useState('')
  const messagePane = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)

  const agents = useQuery({ queryKey: ['agents'], queryFn: () => api<AgentInfo[]>('/agents') })
  const foodAgent = agents.data?.find((agent) => agent.id === 'food')
  const enabled = foodAgent?.enabled ?? false
  const searchEnabled = foodAgent?.capabilities?.includes('google_search') ?? false
  const fetchEnabled = foodAgent?.capabilities?.includes('web_fetch') ?? false
  const history = useQuery({
    queryKey: ['food-sessions'],
    queryFn: () => api<ConversationSummary[]>(sessionPath),
  })

  async function ensureSession() {
    if (sessionId) return sessionId
    const created = await post<Conversation>(sessionPath)
    cache.setQueryData(['food-session', created.id], created)
    setParams({ food_chat: created.id })
    return created.id
  }

  const turn = useAgentTurn({
    agentId: 'food',
    ensureSession,
    onAccepted: () => setDraft(''),
    onFinished: async (_status, id) => {
      try {
        const updated = await api<Conversation>(`${sessionPath}/${id}`)
        cache.setQueryData(['food-session', id], updated)
      } finally {
        await Promise.all([
          cache.invalidateQueries({ queryKey: ['food-session', id] }),
          cache.invalidateQueries({ queryKey: ['food-sessions'] }),
        ])
      }
    },
  })

  const conversation = useQuery({
    queryKey: ['food-session', sessionId],
    queryFn: () => api<Conversation>(`${sessionPath}/${sessionId}`),
    enabled: Boolean(sessionId) && !turn.isRunning,
    staleTime: 30_000,
    retry: false,
  })

  const messages = conversation.data?.messages ?? []
  const activeText = turn.activeRequest?.text
  const acceptedUserSaved = messages.some(
    (message) =>
      message.role === 'user' &&
      message.text === activeText &&
      message.created_at * 1000 >= (turn.startedAt ?? 0) - 1000,
  )
  const pendingText =
    (turn.sessionId === sessionId || (!sessionId && turn.sessionId)) && !acceptedUserSaved
      ? (activeText ?? null)
      : null
  const busy = turn.isRunning || (Boolean(sessionId) && conversation.isPending)
  const composerDisabled = busy || !enabled
  const sendDisabled = busy || !enabled || !draft.trim() || conversation.isError

  useEffect(() => {
    const pane = messagePane.current
    if (pane) pane.scrollTo({ top: pane.scrollHeight, behavior: 'auto' })
  }, [messages.length, turn.isRunning, turn.status?.progress.stage])

  function submit() {
    const text = draft.trim()
    if (!text || busy || !enabled || conversation.isError) return
    turn.send.mutate({ text, request_id: crypto.randomUUID() })
  }

  function selectConversation(id?: string) {
    setParams(id ? { food_chat: id } : {})
    setDraft('')
    turn.send.reset()
  }

  return (
    <div className="agent-page food-agent-page">
      <AgentPageHeader
        eyebrow={`${foodPresentation.name.toUpperCase()} · ${foodPresentation.role.toUpperCase()}`}
        title="Decipher your ingredients, together."
        description="Paste a label or ask about an additive. Nia checks your preferences and explains the evidence in plain language."
        actions={
          <div className="agent-capabilities" aria-label="Available capabilities">
            {searchEnabled && (
              <span className="search-capability">
                <Search size={13} /> Search
              </span>
            )}
            {fetchEnabled && (
              <span className="search-capability">
                <Globe size={13} /> Evidence check
              </span>
            )}
          </div>
        }
      />

      <div className="agent-workspace">
        <SessionRail
          title="Food reviews"
          newLabel="New review"
          disabled={turn.isRunning}
          onNew={() => selectConversation()}
          footer={
            <p className="fine-print">
              Educational guidance only. Always verify ingredients and allergen warnings on the
              physical packaging.
            </p>
          }
        >
          <section className="session-group">
            <h3>
              <MessageSquare size={15} /> Recent reviews
            </h3>
            <ErrorMessage error={history.error} />
            {history.isPending && <p className="muted">Loading reviews…</p>}
            {history.data?.length ? (
              <div className="history-list">
                {history.data.map((item) => (
                  <button
                    key={item.id}
                    data-close-session-rail
                    aria-current={sessionId === item.id ? 'page' : undefined}
                    className={`history-item ${sessionId === item.id ? 'current-conversation' : ''}`}
                    disabled={turn.isRunning}
                    onClick={() => selectConversation(item.id)}
                  >
                    <strong>{item.title}</strong>
                    <span>{new Date(item.updated_at * 1000).toLocaleDateString()} · Continue</span>
                  </button>
                ))}
              </div>
            ) : (
              history.isSuccess && <p className="muted">Your reviews will appear here.</p>
            )}
          </section>

          <section className="session-group session-help">
            <span className="eyebrow">NIA CAN HELP WITH</span>
            <ul>
              <li>Ingredient and E-number explanations</li>
              <li>Allergy and age-context checks</li>
              <li>Country regulation comparisons</li>
            </ul>
            <Link className="text-link" to="/profile" data-close-session-rail>
              Edit food preferences →
            </Link>
          </section>

          {onSwitchToScanner && (
            <button
              className="secondary session-tool-button"
              type="button"
              data-close-session-rail
              onClick={onSwitchToScanner}
            >
              <ScanLine size={16} /> Scan a barcode or photo
            </button>
          )}
        </SessionRail>

        <div className="agent-workspace-primary">
          <section className="panel conversation-panel" aria-label="Nia food guide conversation">
            <div className="conversation-heading">
              <div>
                <span className="stylist-avatar food-avatar">
                  <Utensils size={18} />
                </span>
                <div>
                  <h2>
                    {foodPresentation.name} · {foodPresentation.role}
                  </h2>
                  <span className="muted">Ingredients, preferences and evidence</span>
                </div>
              </div>
              <span className={`agent-availability ${enabled ? 'is-ready' : ''}`}>
                {enabled ? 'Ready' : 'Offline'}
              </span>
            </div>

            <ErrorMessage error={agents.error} />
            {conversation.isError && (
              <div className="notice error conversation-load-error" role="alert">
                <span>{conversation.error.message}</span>
                <button
                  className="text-button"
                  type="button"
                  onClick={() => void conversation.refetch()}
                >
                  Try loading again
                </button>
              </div>
            )}
            {agents.isSuccess && !enabled && (
              <div className="notice">
                Live food chat is not enabled in this environment. Configure the Food agent on the
                server, then refresh this page.
              </div>
            )}

            <div
              ref={messagePane}
              className="conversation-messages"
              role="log"
              aria-label="Food conversation messages"
              aria-live="polite"
            >
              {!sessionId && !pendingText && (
                <div className="conversation-welcome">
                  <div className="welcome-spark food-avatar">
                    <Sparkles size={29} strokeWidth={1.3} />
                  </div>
                  <h3>What ingredients are we looking at today?</h3>
                  <p>
                    Paste the label or ask about an additive. Nia will use your saved preferences
                    and show sources when evidence is checked.
                  </p>
                  <div className="conversation-starters">
                    {starters.map((text) => (
                      <button
                        className="secondary"
                        key={text}
                        disabled={busy || !enabled}
                        onClick={() => {
                          setDraft(text)
                          composer.current?.focus()
                        }}
                      >
                        {text}
                        <span aria-hidden="true">→</span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {sessionId && conversation.isPending && !turn.isRunning && (
                <p className="chat-loading">Loading your review…</p>
              )}
              {sessionId && conversation.isSuccess && !messages.length && !pendingText && (
                <p className="chat-loading">Paste an ingredient list or ask Nia a question.</p>
              )}
              {messages.map((message) => (
                <AgentMessage
                  key={message.id}
                  message={message}
                  agentName={`${foodPresentation.name} · ${foodPresentation.role}`}
                  icon={<Utensils size={14} />}
                />
              ))}
              {pendingText && (
                <>
                  <article className="chat-message from-user">
                    <div className="message-author">
                      <strong>You</strong>
                    </div>
                    <p className="user-message-text">{pendingText}</p>
                  </article>
                  <AgentProgress
                    agentName="Nia is working"
                    startedAt={turn.startedAt}
                    stage={turn.status?.progress.stage}
                    label={turn.status?.progress.label}
                    stages={foodProgress}
                  />
                </>
              )}
            </div>

            {turn.pollError && turn.activeRequest && (
              <div className="notice amber progress-connection-notice" role="status">
                <span>Your review is still running, but progress could not be refreshed.</span>
                <button
                  className="text-button"
                  type="button"
                  onClick={() => void turn.retryProgress()}
                >
                  Reconnect
                </button>
              </div>
            )}
            <ErrorMessage error={turn.send.error} />
            <form
              className="chat-composer"
              onSubmit={(event) => {
                event.preventDefault()
                submit()
              }}
            >
              <label className="sr-only" htmlFor="food-message">
                Message Nia
              </label>
              <textarea
                id="food-message"
                ref={composer}
                rows={2}
                maxLength={4000}
                disabled={composerDisabled}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="Paste an ingredient list or ask Nia a question…"
                onKeyDown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                    event.preventDefault()
                    submit()
                  }
                }}
              />
              <button aria-label="Send message" disabled={sendDisabled}>
                <ArrowUp size={21} />
              </button>
            </form>
            <p className="fine-print chat-footer-note">
              Nia can make mistakes. Check the original packaging for ingredients and allergen
              warnings.
            </p>
          </section>
        </div>
      </div>
    </div>
  )
}
