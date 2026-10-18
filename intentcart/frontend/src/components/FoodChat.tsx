import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { ArrowUp, Globe, MessageSquare, Plus, Search, Sparkles, Utensils } from 'lucide-react'
import { api, post } from '../lib/api'
import type { AgentInfo, Conversation, ConversationSummary } from '../lib/conversations'
import { AgentMessage } from './AgentMessage'
import { ErrorMessage, PageTitle } from './Feedback'

const sessionPath = '/agents/food/sessions'
const starters = [
  'Hi! How can you help me check my food ingredients?',
  'Can you review the ingredients of my snack bar?',
  'What is E171 (Titanium Dioxide) and why is it banned in Europe?',
  'Check this cereal for my 4-year-old child: Whole grain wheat, sugar, malt extract, BHT.',
]

export function FoodChat({ onSwitchToScanner }: { onSwitchToScanner?: () => void }) {
  const cache = useQueryClient()
  const [params, setParams] = useSearchParams()
  const sessionId = params.get('food_chat')
  const [draft, setDraft] = useState('')
  const end = useRef<HTMLDivElement>(null)
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

  const send = useMutation({
    retry: false,
    mutationFn: async (body: { text: string; request_id: string }) => {
      let id = sessionId
      if (!id) {
        const created = await post<Conversation>(sessionPath)
        id = created.id
        cache.setQueryData(['food-session', id], created)
        setParams({ food_chat: id })
      }
      try {
        const conversation = await post<Conversation>(`${sessionPath}/${id}/messages`, body)
        cache.setQueryData(['food-session', id], conversation)
        return conversation
      } finally {
        void cache.invalidateQueries({ queryKey: ['food-session', id] })
        void cache.invalidateQueries({ queryKey: ['food-sessions'] })
      }
    },
  })

  const conversation = useQuery({
    queryKey: ['food-session', sessionId],
    queryFn: () => api<Conversation>(`${sessionPath}/${sessionId}`),
    enabled: Boolean(sessionId) && !send.isPending,
    staleTime: 30_000,
    retry: false,
  })

  const messages = conversation.data?.messages ?? []
  const pendingText = send.isPending ? send.variables.text : null
  const busy = send.isPending || (Boolean(sessionId) && conversation.isPending)
  const composerDisabled = busy || !enabled
  const sendDisabled = busy || !enabled || !draft.trim() || conversation.isError

  useEffect(() => {
    end.current?.scrollIntoView({ block: 'nearest', behavior: 'instant' })
  }, [messages.length, send.isPending])

  useEffect(() => {
    // #region agent log
    fetch('http://127.0.0.1:7755/ingest/3c3b3e8e-46ba-4378-8d38-854e39ade4a8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d1c5c0'},body:JSON.stringify({sessionId:'d1c5c0',runId:'pre-fix',hypothesisId:'A',location:'FoodChat.tsx:state',message:'composer_state',data:{enabled,busy,sendPending:send.isPending,sendError:Boolean(send.error),conversationPending:conversation.isPending,conversationError:Boolean(conversation.isError),sessionId:Boolean(sessionId),sendDisabled,composerDisabled,errorCount:messages.filter((m)=>m.status==='error').length},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
  }, [enabled, busy, send.isPending, send.error, conversation.isPending, conversation.isError, sessionId, sendDisabled, composerDisabled, messages])

  function submit() {
    const text = draft.trim()
    const blocked = !text || busy || !enabled || conversation.isError
    // #region agent log
    fetch('http://127.0.0.1:7755/ingest/3c3b3e8e-46ba-4378-8d38-854e39ade4a8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d1c5c0'},body:JSON.stringify({sessionId:'d1c5c0',runId:'pre-fix',hypothesisId:'A',location:'FoodChat.tsx:submit',message:'submit_attempt',data:{blocked,reasons:{empty:!text,busy,disabled:!enabled,conversationError:Boolean(conversation.isError)},textLen:text.length},timestamp:Date.now()})}).catch(()=>{});
    // #endregion
    if (blocked) return
    send.mutate({ text, request_id: crypto.randomUUID() }, {
      onError: (error) => {
        // #region agent log
        fetch('http://127.0.0.1:7755/ingest/3c3b3e8e-46ba-4378-8d38-854e39ade4a8',{method:'POST',headers:{'Content-Type':'application/json','X-Debug-Session-Id':'d1c5c0'},body:JSON.stringify({sessionId:'d1c5c0',runId:'pre-fix',hypothesisId:'C',location:'FoodChat.tsx:onError',message:'send_failed',data:{name:error instanceof Error ? error.message.slice(0,80) : 'unknown'},timestamp:Date.now()})}).catch(()=>{});
        // #endregion
      },
    })
    setDraft('')
  }

  function selectConversation(id?: string) {
    setParams(id ? { food_chat: id } : {})
    setDraft('')
    send.reset()
  }

  return (
    <>
      <PageTitle
        eyebrow="THE FOOD COMPANION"
        title="Decipher your ingredients, together."
        description="A friendly conversational guide to decode food labels, demystify chemical additive terms, identify good vs bad ingredients, and check country regulations."
      />

      <div className="style-chat-layout">
        <section className="panel conversation-panel" aria-label="Food companion conversation">
          <div className="conversation-heading">
            <div>
              <span className="stylist-avatar" style={{ background: '#eaf4e6', color: '#2d6a4f' }}>
                <Utensils size={18} />
              </span>
              <div>
                <h2>Your food companion</h2>
                <span className="muted">Demystifying ingredients &amp; regulations</span>
              </div>
            </div>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
              {searchEnabled && (
                <span className="search-capability">
                  <Search size={13} /> Google Search
                </span>
              )}
              {fetchEnabled && (
                <span className="search-capability">
                  <Globe size={13} /> Official Evidence Fetch
                </span>
              )}
            </div>
          </div>

          <ErrorMessage error={agents.error || conversation.error} />
          {agents.isSuccess && !enabled && (
            <div className="notice">
              Live conversational food chat is not enabled in this environment. Set{' '}
              <code>FOOD_AGENT_MODE=gemini</code> in <code>backend/.env</code> and configure
              Vertex AI with a local Google Cloud login or a Gemini API key. Restart the backend
              after changing these settings, then refresh this page.
            </div>
          )}

          <div
            className="conversation-messages"
            role="log"
            aria-label="Food conversation messages"
            aria-live="polite"
          >
            {!sessionId && !pendingText && (
              <div className="conversation-welcome">
                <div className="welcome-spark" style={{ background: '#eaf4e6', color: '#2d6a4f' }}>
                  <Sparkles size={29} strokeWidth={1.3} />
                </div>
                <h3>What ingredients are we looking at today?</h3>
                <p>
                  Greet me, paste an ingredient list, or ask about any additive. I will help decode
                  the terms, check your allergies &amp; age suitability, identify good vs bad ingredients,
                  and compare country regulations.
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
                      <span aria-hidden="true">↗</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {sessionId && conversation.isPending && !send.isPending && (
              <p className="chat-loading">Loading your food review conversation…</p>
            )}

            {sessionId && conversation.isSuccess && !messages.length && !pendingText && (
              <p className="chat-loading">
                Say hello or paste an ingredient list to get started.
              </p>
            )}

            {messages.map((message) => (
              <AgentMessage
                key={message.id}
                message={message}
                agentName="Food companion"
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
                <div className="agent-working" role="status">
                  <span className="working-dot" /> Your food companion is investigating…
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
            <label className="sr-only" htmlFor="food-message">
              Message your food companion
            </label>
            <textarea
              id="food-message"
              ref={composer}
              rows={2}
              maxLength={4000}
              disabled={composerDisabled}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="Paste an ingredient list, mention a snack, or say hello…"
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  submit()
                }
              }}
            />
            <button
              aria-label="Send message"
              disabled={sendDisabled}
            >
              <ArrowUp size={21} />
            </button>
          </form>

          <p className="fine-print chat-footer-note">
            Educational food ingredient and regulation review. Always check physical packaging for
            official allergen warnings and ingredients.
          </p>
        </section>

        <aside className="stack conversation-sidebar">
          <button
            className="secondary"
            disabled={send.isPending}
            onClick={() => selectConversation()}
          >
            <Plus size={16} /> Start a new review
          </button>

          <section className="panel tinted">
            <span className="eyebrow">WHAT WE EXAMINE</span>
            <h3>
              Good vs. Bad.
              <br />
              Decoded for you.
            </h3>
            <p style={{ fontSize: '13px', lineHeight: '1.5' }}>
              • <strong>Confirm &amp; Clean:</strong> Clarify confusing terms &amp; E-numbers.
              <br />
              • <strong>Allergies &amp; Age:</strong> Check suitability for your family.
              <br />
              • <strong>Good vs. Bad:</strong> Spot nutritious components vs. additives of concern.
              <br />
              • <strong>Regulations:</strong> Compare US (FDA), EU (EFSA), UK (FSA) &amp; India (FSSAI).
            </p>
            <Link className="text-link" to="/profile">
              Edit allergy &amp; profile preferences ↗
            </Link>
          </section>

          {onSwitchToScanner && (
            <button className="secondary" type="button" onClick={onSwitchToScanner}>
              📷 Use Barcode or Photo Scanner ↗
            </button>
          )}

          <section className="panel">
            <h3>
              <MessageSquare size={16} /> Recent reviews
            </h3>
            <ErrorMessage error={history.error} />
            {history.isPending && <p>Loading reviews…</p>}
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
              history.isSuccess && <p>Your past food reviews will appear here.</p>
            )}
          </section>
        </aside>
      </div>
    </>
  )
}

