import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUp, ImagePlus, LayoutGrid, MessageSquare, Search, Sparkles, X } from 'lucide-react'
import { api, post, upload } from '../lib/api'
import { useAgentTurn } from '../lib/agentTurns'
import { agents as agentProfiles } from '../lib/agents'
import type { AgentInfo, Conversation, ConversationSummary } from '../lib/conversations'
import { AgentMessage } from '../components/AgentMessage'
import { AgentPageHeader } from '../components/AgentPageHeader'
import { AgentProgress } from '../components/AgentProgress'
import { AuthedImage } from '../components/BoardMedia'
import { ErrorMessage } from '../components/Feedback'
import { LookPanel } from '../components/LookPanel'
import { SessionRail } from '../components/SessionRail'
import '../look-board.css'

const sessionPath = '/agents/stylist/sessions'
const stylistPresentation = agentProfiles.stylist
const starters = [
  'Help me recreate this Mehendi look with affordable accessories.',
  "I want an outfit for my sister's mehendi.",
  'Build a smart-casual work dinner look under ₹5,000.',
]
const imageTypes = ['image/jpeg', 'image/png', 'image/webp']
const stylistProgress = [
  { id: 'queued', label: 'Waiting to start' },
  { id: 'understanding', label: 'Understanding your request' },
  { id: 'planning', label: 'Planning the next steps' },
  { id: 'searching', label: 'Searching stores and sources' },
  { id: 'preparing', label: 'Preparing your answer' },
]

export function ShopLook() {
  const cache = useQueryClient()
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('chat')
  const [draft, setDraft] = useState('')
  const [attachments, setAttachments] = useState<string[]>([])
  const [view, setView] = useState<'chat' | 'board'>('chat')
  const messagePane = useRef<HTMLDivElement>(null)
  const composer = useRef<HTMLTextAreaElement>(null)
  const filePicker = useRef<HTMLInputElement>(null)

  const agents = useQuery({ queryKey: ['agents'], queryFn: () => api<AgentInfo[]>('/agents') })
  const stylist = agents.data?.find((agent) => agent.id === 'stylist')
  const enabled = stylist?.enabled ?? false
  const capabilities = stylist?.capabilities ?? []
  const searchEnabled = capabilities.includes('google_search')
  const history = useQuery({
    queryKey: ['stylist-sessions'],
    queryFn: () => api<ConversationSummary[]>(sessionPath),
  })

  async function ensureSession() {
    if (sessionId) return sessionId
    const created = await post<Conversation>(sessionPath)
    cache.setQueryData(['stylist-session', created.id], created)
    setParams({ chat: created.id })
    return created.id
  }

  const attach = useMutation({
    retry: false,
    mutationFn: async (file: File) => {
      if (!imageTypes.includes(file.type)) throw new Error('Use a JPEG, PNG or WebP image.')
      if (file.size > 5 * 1024 * 1024) throw new Error('Choose an image smaller than 5 MB.')
      const id = await ensureSession()
      const saved = await upload<{ name: string }>(
        `${sessionPath}/${id}/attachments`,
        'image',
        file,
      )
      return saved.name
    },
    onSuccess: (name) => setAttachments((current) => [...current, name].slice(-3)),
  })

  const turn = useAgentTurn<{ text: string; request_id: string; attachments: string[] }>({
    agentId: 'stylist',
    ensureSession,
    onAccepted: () => {
      setDraft('')
      setAttachments([])
    },
    onFinished: async (_status, id) => {
      try {
        const updated = await api<Conversation>(`${sessionPath}/${id}`)
        cache.setQueryData(['stylist-session', id], updated)
      } finally {
        await Promise.all([
          cache.invalidateQueries({ queryKey: ['stylist-session', id] }),
          cache.invalidateQueries({ queryKey: ['stylist-sessions'] }),
          cache.invalidateQueries({ queryKey: ['look'] }),
        ])
      }
    },
  })

  const conversation = useQuery({
    queryKey: ['stylist-session', sessionId],
    queryFn: () => api<Conversation>(`${sessionPath}/${sessionId}`),
    enabled: Boolean(sessionId) && !turn.isRunning,
    staleTime: 30_000,
    retry: false,
  })

  const messages = conversation.data?.messages ?? []
  const lookId = conversation.data?.look_id ?? null
  const acceptedUserSaved = messages.some(
    (message) =>
      message.role === 'user' &&
      message.text === turn.activeRequest?.text &&
      message.created_at * 1000 >= (turn.startedAt ?? 0) - 1000,
  )
  const pending =
    (turn.sessionId === sessionId || (!sessionId && turn.sessionId)) && !acceptedUserSaved
      ? turn.activeRequest
      : null
  const busy = turn.isRunning || attach.isPending || (Boolean(sessionId) && conversation.isPending)

  useEffect(() => {
    const pane = messagePane.current
    if (pane) pane.scrollTo({ top: pane.scrollHeight, behavior: 'auto' })
  }, [messages.length, turn.isRunning, turn.status?.progress.stage])

  function submit() {
    const text = draft.trim()
    if (!text || busy || !enabled || conversation.isError) return
    const body = { text, request_id: crypto.randomUUID(), attachments }
    turn.send.mutate(body)
  }

  function selectConversation(id?: string) {
    setParams(id ? { chat: id } : {})
    setDraft('')
    setAttachments([])
    setView('chat')
    turn.send.reset()
    attach.reset()
  }

  function refineLook(prompt: string) {
    setDraft(prompt)
    setView('chat')
    window.requestAnimationFrame(() => composer.current?.focus())
  }

  const imagePath = (name: string) => `${sessionPath}/${sessionId}/artifacts/${name}`

  const chat = (
    <section className="panel conversation-panel" aria-label="Mira personal stylist conversation">
      <div className="conversation-heading">
        <div>
          <span className="stylist-avatar">
            <Sparkles size={18} />
          </span>
          <div>
            <h2>
              {stylistPresentation.name} · {stylistPresentation.role}
            </h2>
            <span className="muted">From an idea to a complete look</span>
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
          <button className="text-button" type="button" onClick={() => void conversation.refetch()}>
            Try loading again
          </button>
        </div>
      )}
      {agents.isSuccess && !enabled && (
        <div className="notice">
          Live styling chat is not enabled in this environment. You can still explore the{' '}
          <Link className="text-link" to="/clothes/board">
            sample look board →
          </Link>
        </div>
      )}

      <div
        ref={messagePane}
        className="conversation-messages"
        role="log"
        aria-label="Style conversation messages"
        aria-live="polite"
      >
        {!sessionId && !pending && (
          <div className="conversation-welcome">
            <div className="welcome-spark">
              <Sparkles size={29} strokeWidth={1.3} />
            </div>
            <h3>What are you dressing for?</h3>
            <p>
              Tell Mira the occasion, your total budget, and what you need—or attach a look you
              love.
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
                  <span aria-hidden="true">→</span>
                </button>
              ))}
            </div>
          </div>
        )}
        {sessionId && conversation.isPending && !turn.isRunning && (
          <p className="chat-loading">Loading your conversation…</p>
        )}
        {sessionId && conversation.isSuccess && !messages.length && !pending && (
          <p className="chat-loading">Tell Mira about the occasion to get started.</p>
        )}
        {messages.map((message) => (
          <div key={message.id}>
            <AgentMessage
              message={message}
              agentName={`${stylistPresentation.name} · ${stylistPresentation.role}`}
            />
            {message.attachments && message.attachments.length > 0 && sessionId && (
              <div className="message-attachments">
                {message.attachments.map((name) => (
                  <AuthedImage key={name} path={imagePath(name)} alt="Your reference" />
                ))}
              </div>
            )}
          </div>
        ))}
        {pending && (
          <>
            <article className="chat-message from-user">
              <div className="message-author">
                <strong>You</strong>
              </div>
              <p className="user-message-text">{pending.text}</p>
              {pending.attachments.length > 0 && (
                <p className="fine-print">
                  {pending.attachments.length} reference image
                  {pending.attachments.length > 1 ? 's' : ''} attached
                </p>
              )}
            </article>
            <AgentProgress
              agentName="Mira is working"
              startedAt={turn.startedAt}
              stage={turn.status?.progress.stage}
              label={turn.status?.progress.label}
              stages={stylistProgress}
            />
          </>
        )}
      </div>

      {turn.pollError && turn.activeRequest && (
        <div className="notice amber progress-connection-notice" role="status">
          <span>Your look is still running, but progress could not be refreshed.</span>
          <button className="text-button" type="button" onClick={() => void turn.retryProgress()}>
            Reconnect
          </button>
        </div>
      )}
      <ErrorMessage error={turn.send.error || attach.error} />
      {attachments.length > 0 && sessionId && (
        <div className="composer-attachments">
          {attachments.map((name) => (
            <span key={name} className="attachment-chip">
              <AuthedImage path={imagePath(name)} alt="Attached reference" />
              <button
                type="button"
                aria-label="Remove image"
                onClick={() => setAttachments((current) => current.filter((item) => item !== name))}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <form
        className="chat-composer"
        onSubmit={(event) => {
          event.preventDefault()
          submit()
        }}
      >
        <input
          ref={filePicker}
          type="file"
          accept={imageTypes.join(',')}
          hidden
          onChange={(event) => {
            const file = event.target.files?.[0]
            if (file) attach.mutate(file)
            event.target.value = ''
          }}
        />
        <button
          type="button"
          className="attach-button"
          aria-label="Attach a reference image"
          title="Attach a reference image"
          disabled={busy || !enabled || attachments.length >= 3}
          onClick={() => filePicker.current?.click()}
        >
          <ImagePlus size={19} />
        </button>
        <label className="sr-only" htmlFor="style-message">
          Message Mira
        </label>
        <textarea
          id="style-message"
          ref={composer}
          rows={2}
          maxLength={4000}
          disabled={busy || !enabled}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={
            attachments.length ? 'What should Mira change?' : 'Describe the occasion or look…'
          }
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault()
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
          ? 'Prices and availability can change. Confirm the final details with the store.'
          : 'Style planning is available; live product search is currently unavailable.'}
      </p>
    </section>
  )

  return (
    <div className="agent-page stylist-agent-page">
      <AgentPageHeader
        eyebrow={`${stylistPresentation.name.toUpperCase()} · ${stylistPresentation.role.toUpperCase()}`}
        title="Let's find your kind of look."
        description="Share an occasion, photo, and total budget. Mira plans the pieces, explains the split, and finds options that work together."
        actions={
          searchEnabled ? (
            <span className="search-capability">
              <Search size={13} /> Live store search
            </span>
          ) : undefined
        }
      />

      <div className={`agent-workspace ${lookId ? 'has-look-board' : ''}`}>
        <SessionRail
          title="Saved looks"
          newLabel="New look"
          disabled={turn.isRunning}
          onNew={() => selectConversation()}
          footer={
            <Link className="text-link" to="/clothes/board">
              Explore the sample board →
            </Link>
          }
        >
          <section className="session-group">
            <h3>
              <MessageSquare size={15} /> Recent looks
            </h3>
            <ErrorMessage error={history.error} />
            {history.isPending && <p className="muted">Loading looks…</p>}
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
              history.isSuccess && <p className="muted">Your looks will appear here.</p>
            )}
          </section>

          <section className="session-group session-help">
            <span className="eyebrow">HOW IT WORKS</span>
            <ol>
              <li>Share the occasion and total budget.</li>
              <li>Review Mira's item and budget plan.</li>
              <li>Choose products or refine the whole look.</li>
            </ol>
            <Link className="text-link" to="/profile" data-close-session-rail>
              Edit style preferences →
            </Link>
          </section>
        </SessionRail>

        <div className="agent-workspace-primary">
          {lookId && sessionId ? (
            <>
              <div className="view-switch" role="tablist" aria-label="Workspace view">
                <button
                  id="look-board-tab"
                  role="tab"
                  aria-controls="look-board-panel"
                  aria-selected={view === 'board'}
                  className={view === 'board' ? 'selected' : ''}
                  onClick={() => setView('board')}
                >
                  <LayoutGrid size={14} /> Look board
                </button>
                <button
                  id="look-chat-tab"
                  role="tab"
                  aria-controls="look-chat-panel"
                  aria-selected={view === 'chat'}
                  className={view === 'chat' ? 'selected' : ''}
                  onClick={() => setView('chat')}
                >
                  <MessageSquare size={14} /> Chat with Mira
                </button>
              </div>
              <div className={`style-chat-layout with-board show-${view}`}>
                <div
                  id="look-board-panel"
                  className="board-column"
                  role="tabpanel"
                  aria-labelledby="look-board-tab"
                >
                  <LookPanel lookId={lookId} sessionId={sessionId} onRefine={refineLook} />
                </div>
                <div
                  id="look-chat-panel"
                  className="chat-column"
                  role="tabpanel"
                  aria-labelledby="look-chat-tab"
                >
                  {chat}
                </div>
              </div>
            </>
          ) : (
            chat
          )}
        </div>
      </div>
    </div>
  )
}
