import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  ArrowUp,
  ImagePlus,
  LayoutGrid,
  MessageSquare,
  Plus,
  Search,
  Sparkles,
  X,
} from 'lucide-react'
import { api, post, upload } from '../lib/api'
import type { AgentInfo, Conversation, ConversationSummary } from '../lib/conversations'
import { AgentMessage } from '../components/AgentMessage'
import { AuthedImage } from '../components/BoardMedia'
import { ErrorMessage, PageTitle } from '../components/Feedback'
import { LookPanel } from '../components/LookPanel'
import '../look-board.css'

const sessionPath = '/agents/stylist/sessions'
const starters = [
  'Help me recreate this Mehendi look, but with more affordable accessories.',
  "I want an outfit for my sister's mehendi.",
  'I need a smart casual look for a work dinner under ₹5,000.',
]
const imageTypes = ['image/jpeg', 'image/png', 'image/webp']

export function ShopLook() {
  const cache = useQueryClient()
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('chat')
  const [draft, setDraft] = useState('')
  const [attachments, setAttachments] = useState<string[]>([])
  const [view, setView] = useState<'chat' | 'board'>('chat')
  const end = useRef<HTMLDivElement>(null)
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
  const send = useMutation({
    retry: false,
    mutationFn: async (body: { text: string; request_id: string; attachments: string[] }) => {
      const id = await ensureSession()
      try {
        const conversation = await post<Conversation>(`${sessionPath}/${id}/messages`, body)
        cache.setQueryData(['stylist-session', id], conversation)
        return conversation
      } finally {
        void cache.invalidateQueries({ queryKey: ['stylist-session', id] })
        void cache.invalidateQueries({ queryKey: ['stylist-sessions'] })
        void cache.invalidateQueries({ queryKey: ['look'] })
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
  const lookId = conversation.data?.look_id ?? null
  const pending = send.isPending ? send.variables : null
  const busy = send.isPending || attach.isPending || (Boolean(sessionId) && conversation.isPending)
  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
  }, [messages.length, send.isPending])

  function submit() {
    const text = draft.trim()
    if (!text || busy || !enabled || conversation.isError) return
    send.mutate({ text, request_id: crypto.randomUUID(), attachments })
    setDraft('')
    setAttachments([])
  }
  function selectConversation(id?: string) {
    setParams(id ? { chat: id } : {})
    setDraft('')
    setAttachments([])
    setView('chat')
    send.reset()
    attach.reset()
  }
  const imagePath = (name: string) => `${sessionPath}/${sessionId}/artifacts/${name}`

  const chat = (
    <section className="panel conversation-panel" aria-label="Shop a look conversation">
      <div className="conversation-heading">
        <div>
          <span className="stylist-avatar">
            <Sparkles size={18} />
          </span>
          <div>
            <h2>Your personal stylist</h2>
            <span className="muted">From an idea to a complete look</span>
          </div>
        </div>
        {searchEnabled && (
          <span className="search-capability">
            <Search size={13} /> Live store search
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
        {!sessionId && !pending && (
          <div className="conversation-welcome">
            <div className="welcome-spark">
              <Sparkles size={29} strokeWidth={1.3} />
            </div>
            <h3>What are you dressing for?</h3>
            <p>
              Describe the occasion or attach a photo of a look you love. We'll build a checklist,
              find matching pieces (including small businesses) and keep it all within budget.
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
        {sessionId && conversation.isSuccess && !messages.length && !pending && (
          <p className="chat-loading">Tell your stylist about the occasion to get started.</p>
        )}
        {messages.map((message) => (
          <div key={message.id}>
            <AgentMessage message={message} agentName="IntentCart stylist" />
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
            <div className="agent-working" role="status">
              <span className="working-dot" /> Your stylist is working on it…
            </div>
          </>
        )}
        <div ref={end} />
      </div>
      <ErrorMessage error={send.error || attach.error} />
      {attachments.length > 0 && sessionId && (
        <div className="composer-attachments">
          {attachments.map((name) => (
            <span key={name} className="attachment-chip">
              <AuthedImage path={imagePath(name)} alt="Attached reference" />
              <button
                type="button"
                aria-label="Remove image"
                onClick={() => setAttachments((current) => current.filter((n) => n !== name))}
              >
                <X size={12} />
              </button>
            </span>
          ))}
        </div>
      )}
      <form
        className="chat-composer"
        onSubmit={(e) => {
          e.preventDefault()
          submit()
        }}
      >
        <input
          ref={filePicker}
          type="file"
          accept={imageTypes.join(',')}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) attach.mutate(file)
            e.target.value = ''
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
          placeholder={
            attachments.length
              ? 'What should we do with this look?'
              : "Describe the occasion or a look you'd like…"
          }
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
          ? 'Products are checked on each store page. Prices and stock can change; confirm with the store.'
          : 'Style ideas and outfit planning. Live product search is currently unavailable.'}
      </p>
    </section>
  )

  const historyPanel = (
    <section className="panel">
      <h3>
        <MessageSquare size={16} /> Recent looks
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
              <span>{new Date(item.updated_at * 1000).toLocaleDateString()} · Continue ↗</span>
            </button>
          ))}
        </div>
      ) : (
        history.isSuccess && <p>Your looks will appear here.</p>
      )}
    </section>
  )

  const sidebar = (
    <aside className="stack conversation-sidebar">
      <button className="secondary" disabled={send.isPending} onClick={() => selectConversation()}>
        <Plus size={16} /> Start a new look
      </button>
      <section className="panel tinted">
        <span className="eyebrow">HOW IT WORKS</span>
        <h3>
          Idea → checklist →
          <br />
          the complete look.
        </h3>
        <p>
          Share an occasion, a photo and your budget. Approve a checklist, then choose pieces one by
          one as matching products appear on your board.
        </p>
        <Link className="text-link" to="/profile">
          Edit style preferences ↗
        </Link>
      </section>
      {historyPanel}
      <Link className="text-link sample-board-link" to="/clothes/board">
        Explore the sample look board ↗
      </Link>
    </aside>
  )

  return (
    <>
      <PageTitle
        eyebrow="SHOP A LOOK"
        title="Let's find your kind of look."
        description="Start with an occasion, a photo, or a style you love. Your stylist builds the checklist, finds the pieces and keeps you on budget."
      />
      {lookId && sessionId ? (
        <>
          <div className="view-switch" role="tablist" aria-label="Show">
            <button
              role="tab"
              aria-selected={view === 'chat'}
              className={view === 'chat' ? 'selected' : ''}
              onClick={() => setView('chat')}
            >
              <MessageSquare size={14} /> Chat
            </button>
            <button
              role="tab"
              aria-selected={view === 'board'}
              className={view === 'board' ? 'selected' : ''}
              onClick={() => setView('board')}
            >
              <LayoutGrid size={14} /> Look board
            </button>
          </div>
          <div className={`style-chat-layout with-board show-${view}`}>
            <div className="stack chat-column">
              {chat}
              <div className="board-tools">
                <button
                  className="secondary"
                  disabled={send.isPending}
                  onClick={() => selectConversation()}
                >
                  <Plus size={16} /> Start a new look
                </button>
              </div>
              {historyPanel}
            </div>
            <div className="board-column">
              <LookPanel lookId={lookId} sessionId={sessionId} />
            </div>
          </div>
        </>
      ) : (
        <div className="style-chat-layout">
          {chat}
          {sidebar}
        </div>
      )}
    </>
  )
}
