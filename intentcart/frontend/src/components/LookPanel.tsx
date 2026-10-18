import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BadgeCheck,
  Check,
  ExternalLink,
  Heart,
  Link2,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Shirt,
  SlidersHorizontal,
  Sparkles,
  Star,
  Store,
  TrendingDown,
  X,
} from 'lucide-react'
import { api } from '../lib/api'
import {
  money,
  type ChecklistItem,
  type FeedbackReason,
  type Look,
  type Product,
  type SellerLabel,
} from '../lib/types'
import { safeWebUrl } from '../lib/conversations'
import { ErrorMessage } from './Feedback'
import { AuthedImage, PinterestPin, RemoteImage } from './BoardMedia'

const sellerText: Record<SellerLabel, string> = {
  verified_small_business: 'Verified small business',
  independent: 'Independent store',
  marketplace: 'Marketplace',
  brand: 'Brand',
  unknown: '',
}
const statusText = {
  open: 'To choose',
  locked: 'Selected',
  owned: 'You own this',
  removed: 'Removed',
}

function isSearching(look?: Look) {
  return Boolean(
    look?.items.some((item) => item.discovery === 'searching') ||
    look?.budget_plan?.status === 'surveying',
  )
}

type LookMutation = {
  url: string
  body?: unknown
  method?: 'POST' | 'PATCH'
}

type RefineKind =
  'cheaper' | 'more_formal' | 'more_casual' | 'change_colour' | 'popular_stores_only' | 'custom'

export function LookPanel({
  lookId,
  sessionId,
  onRefine,
}: {
  lookId: string
  sessionId: string
  /** Draft a chat message for the user, or send it straight away. */
  onRefine: (prompt: string, sendNow?: boolean) => void
}) {
  const cache = useQueryClient()
  const [refineOpen, setRefineOpen] = useState(false)
  const [refinement, setRefinement] = useState('')
  const path = `/clothes/looks/${lookId}`
  const look = useQuery({
    queryKey: ['look', lookId],
    queryFn: () => api<Look>(path),
    refetchInterval: (query) => (isSearching(query.state.data) ? 2500 : false),
  })
  const update = useMutation({
    mutationFn: ({ url, body, method = 'POST' }: LookMutation) =>
      api<Look>(url, {
        method,
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
    onSuccess: (data) => {
      cache.setQueryData(['look', lookId], data)
      setRefinement('')
    },
  })
  const act = (url: string, body?: unknown, method?: 'POST' | 'PATCH') =>
    update.mutate({ url: `${path}${url}`, body, method })
  const refine = (kind: RefineKind, request = '', colour = '') =>
    act('/refine', { kind, request, colour, preserve_selected: true })
  const data = look.data
  if (look.isPending) return <aside className="panel look-panel">Loading your look board…</aside>
  if (!data)
    return (
      <aside className="panel look-panel">
        <ErrorMessage error={look.error} />
      </aside>
    )
  const busy = update.isPending
  const budget = data.brief.total_budget_minor
  const spentShare = budget ? Math.min(100, (data.total_spent_minor / budget) * 100) : 0
  const open = data.items.filter((item) => item.status === 'open')
  return (
    <aside className="look-panel stack" aria-label="Look board">
      <section className="panel summary look-header">
        <div className="look-header-top">
          <div>
            <span className="eyebrow">YOUR LOOK BOARD</span>
            <h2>{data.brief.occasion}</h2>
          </div>
          <div className="look-header-actions">
            {(data.brief.retailer_policy ?? 'popular_first') === 'popular_first' ? (
              <span className="seller-badge brand">
                <Store size={12} /> Popular stores first
              </span>
            ) : (
              <span className="seller-badge independent">
                <Store size={12} />
                {data.brief.retailer_policy === 'independent_only'
                  ? 'Independent stores only'
                  : data.brief.retailer_policy === 'balanced'
                    ? 'Popular + independent'
                    : 'Favouring independent stores'}
              </span>
            )}
            <button
              type="button"
              className="small secondary"
              aria-expanded={refineOpen}
              onClick={() => setRefineOpen((current) => !current)}
            >
              <SlidersHorizontal size={13} /> Update look
            </button>
          </div>
        </div>
        {budget ? (
          <>
            <div className="budget-number">{money(data.remaining_budget_minor)}</div>
            <p>left of {money(budget)}</p>
            <div className="budget-track">
              <div style={{ width: `${spentShare}%` }} />
            </div>
            <div className="summary-row">
              <span>Selected</span>
              <strong>{money(data.total_spent_minor)}</strong>
            </div>
          </>
        ) : (
          <p className="muted small-copy">
            Exploring ideas. Tell Mira your total budget when you are ready to shop.
          </p>
        )}
        {data.analysis?.palette?.length ? (
          <div className="palette-row" aria-label="Palette">
            {data.analysis.palette.map((colour) => (
              <span key={colour}>{colour}</span>
            ))}
          </div>
        ) : null}
      </section>
      {data.budget_plan && budget && (
        <BudgetPlanCard
          key={data.plan_revision ?? data.budget_plan.revision}
          look={data}
          busy={busy}
          onReplan={() => act('/replan')}
        />
      )}
      {refineOpen && (
        <section className="panel refine-look-panel stack compact" aria-label="Update this look">
          <div>
            <span className="eyebrow">REFINE WITH MIRA</span>
            <h3>What should change?</h3>
            <p className="muted small-copy">
              Selected pieces stay in place unless you ask to replace them.
            </p>
          </div>
          <div className="refine-chips" aria-label="Quick refinements">
            <button
              type="button"
              className="secondary small"
              disabled={busy}
              onClick={() => refine('cheaper')}
            >
              Make the full look cheaper
            </button>
            <button
              type="button"
              className="secondary small"
              disabled={busy}
              onClick={() => refine('popular_stores_only')}
            >
              Show popular stores first
            </button>
            <button
              type="button"
              className="secondary small"
              disabled={busy}
              onClick={() => refine('change_colour')}
            >
              Change the colour palette
            </button>
            <button
              type="button"
              className="secondary small"
              disabled={busy}
              onClick={() => refine('more_formal')}
            >
              Make the look more formal
            </button>
          </div>
          <form
            className="inline-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (!refinement.trim()) return
              refine('custom', refinement.trim())
            }}
          >
            <label className="sr-only" htmlFor={`refine-${lookId}`}>
              Describe the change
            </label>
            <input
              id={`refine-${lookId}`}
              value={refinement}
              maxLength={500}
              onChange={(event) => setRefinement(event.target.value)}
              placeholder="e.g. keep the shirt, find smarter trousers"
            />
            <button disabled={busy || !refinement.trim()}>Update look</button>
          </form>
          <button
            type="button"
            className="text-button"
            onClick={() => onRefine('Help me decide what to change in this look.')}
          >
            Not sure? Discuss it with Mira
          </button>
        </section>
      )}
      <ErrorMessage error={update.error} />
      <Inspiration
        look={data}
        sessionId={sessionId}
        onUse={(number, title) =>
          onRefine(
            `Let's go with idea ${number}${title ? ` (${title})` : ''} as my reference look.`,
            true,
          )
        }
      />
      {data.status === 'exploring' ? (
        !data.inspiration?.length && (
          <section className="panel stack compact">
            <span className="eyebrow">
              <Sparkles size={12} /> GETTING TO KNOW YOUR STYLE
            </span>
            <p className="muted small-copy">
              Answer a few quick questions in the chat, or ask Mira for look ideas from Pinterest
              and fashion sites.
            </p>
            <button
              type="button"
              className="small secondary"
              onClick={() => onRefine('Show me some look ideas first.', true)}
            >
              <Sparkles size={13} /> Show me look ideas
            </button>
          </section>
        )
      ) : data.status === 'awaiting_checklist' ? (
        <ChecklistEditor look={data} busy={busy} act={act} />
      ) : (
        <>
          {data.items.map((item) => (
            <ItemCard key={item.id} item={item} busy={busy} act={act} />
          ))}
          <AddItem busy={busy} onAdd={(category, target) => act('/items', { category, target })} />
          {data.status === 'shopping' && open.length === 0 && (
            <button disabled={busy} onClick={() => act('/assemble')}>
              <Check size={16} /> Finish my look
            </button>
          )}
          {data.status === 'assembled' && <Review look={data} onRefine={onRefine} />}
        </>
      )}
      <p className="fine-print">
        Prices, stock and ratings are read from each store's page when found, and can change. Check
        size, delivery to your PIN and returns with the store before buying. AI concept images are
        illustrations, not products.
      </p>
    </aside>
  )
}

function BudgetPlanCard({
  look,
  busy,
  onReplan,
}: {
  look: Look
  busy: boolean
  onReplan: () => void
}) {
  const plan = look.budget_plan!
  const activeItems = look.items.filter(
    (item) => item.status === 'open' || item.status === 'locked',
  )
  const loading = plan.status === 'surveying'
  const budget = look.brief.total_budget_minor ?? 0
  const shortfall = Math.max(0, plan.minimum_complete_total_minor - budget)

  return (
    <section className={`panel budget-plan budget-plan-${plan.status}`} aria-live="polite">
      <div className="budget-plan-heading">
        <div>
          <span className="eyebrow">SMART BUDGET · PLAN {plan.revision}</span>
          <h3>{loading ? 'Checking realistic prices' : 'How your budget is split'}</h3>
        </div>
        {look.status !== 'awaiting_checklist' && (
          <button
            type="button"
            className="small secondary"
            disabled={busy || loading}
            onClick={onReplan}
          >
            {loading ? <Loader2 size={13} className="spin" /> : <RefreshCw size={13} />}
            Recheck
          </button>
        )}
      </div>

      {loading ? (
        <div className="budget-survey-progress" role="status">
          <span className="budget-survey-pulse" aria-hidden="true" />
          <p>
            Mira is surveying prices for each piece before finalising the split and results. This
            keeps the complete look inside your total budget.
          </p>
        </div>
      ) : (
        <>
          <p className={`budget-plan-note ${plan.feasible === false ? 'warning' : ''}`}>
            {plan.note ||
              (plan.feasible
                ? `Planned total ${money(plan.planned_total_minor)} within your ${money(budget)} budget.`
                : `A complete look may need about ${money(plan.minimum_complete_total_minor)}.`)}
          </p>
          {plan.feasible === false && shortfall > 0 && (
            <p className="budget-shortfall">
              Short by about <strong>{money(shortfall)}</strong>. Remove a piece, use something you
              own, or ask Mira for a cheaper version.
            </p>
          )}
          <div className="budget-split" role="list" aria-label="Budget by item">
            {activeItems.map((item) => (
              <div className="budget-split-row" role="listitem" key={item.id}>
                <div>
                  <strong className="capitalize">{item.category}</strong>
                  {item.price_band && (
                    <span>
                      Typical range {money(item.price_band.low_minor)}–
                      {money(item.price_band.high_minor)}
                      {item.price_band.source === 'market' && item.price_band.sample_count
                        ? ` · ${item.price_band.sample_count} checked`
                        : item.price_band.source === 'selected'
                          ? ' · selected price'
                          : ' · estimated'}
                    </span>
                  )}
                </div>
                <strong>{money(item.planned_budget_minor ?? item.budget_cap_minor)}</strong>
              </div>
            ))}
          </div>
          <div className="budget-plan-totals">
            <span>
              {plan.open_item_count
                ? `${plan.verified_item_count} of ${plan.open_item_count} item ranges use live prices`
                : 'All pieces are resolved'}
            </span>
            <strong>{money(plan.planned_total_minor)} planned</strong>
          </div>
        </>
      )}
    </section>
  )
}

function Inspiration({
  look,
  sessionId,
  onUse,
}: {
  look: Look
  sessionId: string
  onUse: (number: number, title: string) => void
}) {
  const concepts = look.concepts ?? []
  // Numbered in board order so "idea 2" means the same thing to the user and to Mira.
  const ideas = (look.inspiration ?? [])
    .map((idea, index) => ({ idea, number: index + 1 }))
    .filter(({ idea }) => idea.kind === 'pinterest' || idea.image_url)
  if (!concepts.length && !ideas.length) return null
  return (
    <section className="panel inspiration-panel">
      <span className="eyebrow">
        <Sparkles size={12} /> INSPIRATION
      </span>
      {ideas.length > 0 && look.status === 'exploring' && (
        <p className="muted small-copy">
          Pick the ideas you like and Mira will build a shoppable look from them.
        </p>
      )}
      <div className="inspiration-strip">
        {concepts
          .slice()
          .reverse()
          .map((concept) => (
            <figure key={concept.id} className="concept-card">
              <AuthedImage
                path={`/agents/stylist/sessions/${sessionId}/artifacts/${concept.artifact}`}
                alt={concept.caption}
              />
              <figcaption>
                <span className="ai-label">AI concept</span> {concept.caption}
              </figcaption>
            </figure>
          ))}
        {ideas.map(({ idea, number }) => (
          <figure key={idea.id} className="concept-card idea-card">
            <span className="idea-number" aria-label={`Idea ${number}`}>
              {number}
            </span>
            {idea.image_url ? (
              <RemoteImage src={idea.image_url} alt={idea.title || `Idea ${number}`} />
            ) : (
              <PinterestPin url={idea.url} title={idea.title} />
            )}
            <figcaption>
              <a href={safeWebUrl(idea.url)} target="_blank" rel="noopener noreferrer">
                {idea.title || 'Look idea'} · {idea.source || 'Web'} ↗
              </a>
              <button
                type="button"
                className="small secondary"
                onClick={() => onUse(number, idea.title)}
              >
                <Check size={13} /> Use this look
              </button>
            </figcaption>
          </figure>
        ))}
      </div>
    </section>
  )
}

function ChecklistEditor({
  look,
  busy,
  act,
}: {
  look: Look
  busy: boolean
  act: (url: string, body?: unknown) => void
}) {
  const [choices, setChoices] = useState<Record<string, 'open' | 'owned' | 'removed'>>({})
  useEffect(() => {
    setChoices(
      Object.fromEntries(
        look.items.map((item) => [item.id, item.status === 'locked' ? 'open' : item.status]),
      ) as Record<string, 'open' | 'owned' | 'removed'>,
    )
  }, [look.revision, look.items])
  const items = look.items.map((item) => ({
    category: item.category,
    target: item.target ?? '',
    status: choices[item.id] ?? 'open',
  }))
  return (
    <section className="panel stack compact">
      <div>
        <span className="eyebrow">STEP 3 · YOUR CHECKLIST</span>
        <h3>Review the pieces for this look</h3>
        <p className="muted small-copy">
          Mark anything you already own or don't need, add pieces, then start shopping.
        </p>
      </div>
      {look.items.length === 0 && <p className="muted">Your stylist will propose pieces here.</p>}
      {look.items.map((item) => (
        <div className="checklist-row" key={item.id}>
          <div>
            <strong className="capitalize">{item.category}</strong>
            {item.target && <p className="muted small-copy">{item.target}</p>}
          </div>
          <select
            aria-label={`${item.category} status`}
            value={choices[item.id] ?? 'open'}
            onChange={(e) =>
              setChoices({ ...choices, [item.id]: e.target.value as 'open' | 'owned' | 'removed' })
            }
          >
            <option value="open">Shop for this</option>
            <option value="owned">I own this</option>
            <option value="removed">Not needed</option>
          </select>
        </div>
      ))}
      <AddItem busy={busy} onAdd={(category, target) => act('/items', { category, target })} />
      <button
        disabled={busy || !items.length || items.every((i) => i.status === 'removed')}
        onClick={() => act('/checklist', { confirmed: true, items })}
      >
        <Check size={16} /> Confirm and find products
      </button>
    </section>
  )
}

function AddItem({
  busy,
  onAdd,
}: {
  busy: boolean
  onAdd: (category: string, target: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [category, setCategory] = useState('')
  const [target, setTarget] = useState('')
  if (!open)
    return (
      <button className="text-button" onClick={() => setOpen(true)}>
        <Plus size={14} /> Add a piece
      </button>
    )
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!category.trim()) return
        onAdd(category.trim(), target.trim())
        setCategory('')
        setTarget('')
        setOpen(false)
      }}
    >
      <input
        aria-label="Piece"
        placeholder="Piece, e.g. dupatta"
        value={category}
        maxLength={40}
        onChange={(e) => setCategory(e.target.value)}
      />
      <input
        aria-label="Description"
        placeholder="Description (optional)"
        value={target}
        maxLength={300}
        onChange={(e) => setTarget(e.target.value)}
      />
      <button className="small" disabled={busy || !category.trim()}>
        Add
      </button>
      <button type="button" className="small secondary" onClick={() => setOpen(false)}>
        Cancel
      </button>
    </form>
  )
}

function ItemCard({
  item,
  busy,
  act,
}: {
  item: ChecklistItem
  busy: boolean
  act: (url: string, body?: unknown) => void
}) {
  const [linkOpen, setLinkOpen] = useState(false)
  const itemPath = `/items/${item.id}`
  const searching = item.discovery === 'searching'
  const feedback = item.feedback ?? []
  const feedbackCount = feedback.length
  const liked = new Set(feedback.filter((f) => f.sentiment === 'like').map((f) => f.product_id))
  return (
    <section className={`panel item-card status-${item.status}`}>
      <header className="item-card-header">
        <div>
          <span className="eyebrow">{statusText[item.status]}</span>
          <h3 className="capitalize">{item.category}</h3>
          {item.target && <p className="muted small-copy">{item.target}</p>}
        </div>
        {item.status === 'open' && (
          <span className="cap-chip">Up to {money(item.budget_cap_minor)}</span>
        )}
      </header>

      {item.status === 'locked' && item.chosen_product && (
        <div className="stack compact">
          <LiveProductCard product={item.chosen_product} compact />
          <div className="item-actions">
            <button
              className="small secondary"
              disabled={busy}
              onClick={() => act(itemPath, { action: 'swap' })}
            >
              <RefreshCw size={13} /> Swap
            </button>
          </div>
        </div>
      )}

      {(item.status === 'owned' || item.status === 'removed') && (
        <button
          className="text-button"
          disabled={busy}
          onClick={() => act(itemPath, { action: 'reopen' })}
        >
          Shop for this again
        </button>
      )}

      {item.status === 'open' && (
        <div className="stack compact">
          {searching && (
            <p className="discovery-status" role="status">
              <Loader2 size={15} className="spin" /> Searching stores and checking prices…
            </p>
          )}
          {!searching && item.discovery_note && item.discovery !== 'ready' && (
            <div className={`notice ${item.discovery === 'failed' ? 'amber' : ''}`}>
              {item.discovery_note}
            </div>
          )}
          {item.candidates.length > 0 && (
            <div className="product-grid live-grid">
              {item.candidates.map((product) => (
                <LiveProductCard
                  key={product.id}
                  product={product}
                  disabled={busy}
                  liked={liked.has(product.id)}
                  onChoose={() => act(itemPath, { action: 'lock', product_id: product.id })}
                  onFeedback={(sentiment, reasons) =>
                    act(`${itemPath}/feedback`, { product_id: product.id, sentiment, reasons })
                  }
                />
              ))}
            </div>
          )}
          {feedbackCount > 0 && !searching && (
            <button
              className="small"
              disabled={busy}
              onClick={() =>
                act(`${itemPath}/alternatives`, { request: 'more like the ones I liked' })
              }
            >
              <Sparkles size={13} /> Find more using your feedback ({feedbackCount})
            </button>
          )}
          {item.boutiques && item.boutiques.length > 0 && (
            <div className="boutiques">
              <span className="eyebrow">
                <MapPin size={12} /> LOCAL BOUTIQUES
              </span>
              <ul>
                {item.boutiques.map((shop) => (
                  <li key={shop.name}>
                    {shop.url ? (
                      <a href={safeWebUrl(shop.url)} target="_blank" rel="noopener noreferrer">
                        {shop.name} ↗
                      </a>
                    ) : (
                      <strong>{shop.name}</strong>
                    )}
                    {shop.note && <span className="muted"> · {shop.note}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="item-actions wrap">
            {item.discovery !== 'idle' && !searching && (
              <button
                className="small secondary"
                disabled={busy}
                onClick={() => act(`${itemPath}/alternatives`, { request: 'cheaper options' })}
              >
                {item.candidates.length ? <TrendingDown size={13} /> : <RefreshCw size={13} />}
                {item.candidates.length ? 'Cheaper options' : 'Search again'}
              </button>
            )}
            <button
              className="small secondary"
              disabled={busy}
              onClick={() => setLinkOpen(!linkOpen)}
            >
              <Link2 size={13} /> Add a link
            </button>
            <button
              className="small secondary"
              disabled={busy}
              onClick={() => act(itemPath, { action: 'own' })}
            >
              I own this
            </button>
            <button
              className="small secondary"
              disabled={busy}
              onClick={() => act(itemPath, { action: 'remove' })}
            >
              Remove
            </button>
          </div>
          {linkOpen && (
            <LinkForm
              busy={busy}
              onSubmit={(url, price) => {
                act(`${itemPath}/link`, { url, price_minor: price })
                setLinkOpen(false)
              }}
            />
          )}
        </div>
      )}
    </section>
  )
}

function LinkForm({
  busy,
  onSubmit,
}: {
  busy: boolean
  onSubmit: (url: string, price?: number) => void
}) {
  const [url, setUrl] = useState('')
  const [price, setPrice] = useState('')
  const rupees = Number.parseInt(price, 10)
  return (
    <form
      className="inline-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSubmit(url.trim(), Number.isFinite(rupees) && rupees > 0 ? rupees * 100 : undefined)
      }}
    >
      <input
        aria-label="Product link"
        type="url"
        required
        placeholder="https://… product link"
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <input
        aria-label="Price in rupees (if the page has none)"
        inputMode="numeric"
        placeholder="Price ₹ (optional)"
        value={price}
        onChange={(e) => setPrice(e.target.value.replace(/\D/g, ''))}
      />
      <button className="small" disabled={busy || !url.trim()}>
        Add
      </button>
    </form>
  )
}

const dislikeReasons: { id: FeedbackReason; label: string }[] = [
  { id: 'too_expensive', label: 'Too expensive' },
  { id: 'wrong_colour', label: 'Wrong colour' },
  { id: 'too_heavy', label: 'Too heavy / flashy' },
  { id: 'too_plain', label: 'Too plain' },
  { id: 'not_my_style', label: 'Not my style' },
  { id: 'wrong_item', label: 'Wrong item' },
]

export function LiveProductCard({
  product,
  onChoose,
  onFeedback,
  liked,
  disabled,
  compact,
}: {
  product: Product
  onChoose?: () => void
  onFeedback?: (sentiment: 'like' | 'dislike', reasons: FeedbackReason[]) => void
  liked?: boolean
  disabled?: boolean
  compact?: boolean
}) {
  const [asking, setAsking] = useState(false)
  const label = product.seller_label ?? 'unknown'
  const url = safeWebUrl(product.url ?? undefined)
  return (
    <article className={`product-card live-card ${compact ? 'compact' : ''}`}>
      <div className="live-card-media">
        {product.image_url ? (
          <RemoteImage src={product.image_url} alt={product.title} />
        ) : (
          <span className="media-fallback">
            <Shirt size={28} strokeWidth={1.3} />
          </span>
        )}
        {onFeedback && (
          <div className="card-reactions">
            <button
              className={`reaction-button ${liked ? 'active' : ''}`}
              aria-label={`Like ${product.title}`}
              aria-pressed={liked}
              title="More like this"
              disabled={disabled || liked}
              onClick={() => onFeedback('like', [])}
            >
              <Heart size={14} fill={liked ? 'currentColor' : 'none'} />
            </button>
            <button
              className="reaction-button"
              aria-label={`Not for me: ${product.title}`}
              aria-expanded={asking}
              title="Not for me"
              disabled={disabled}
              onClick={() => setAsking((open) => !open)}
            >
              <X size={14} />
            </button>
          </div>
        )}
        {asking && onFeedback && (
          <div className="dislike-reasons" role="group" aria-label="Why not?">
            <span>Why not?</span>
            {dislikeReasons.map((reason) => (
              <button
                key={reason.id}
                type="button"
                disabled={disabled}
                onClick={() => {
                  setAsking(false)
                  onFeedback('dislike', [reason.id])
                }}
              >
                {reason.label}
              </button>
            ))}
            <button
              type="button"
              className="quiet"
              disabled={disabled}
              onClick={() => {
                setAsking(false)
                onFeedback('dislike', [])
              }}
            >
              Just hide it
            </button>
          </div>
        )}
      </div>
      <div className="product-info">
        <span className="eyebrow">{product.retailer}</span>
        <h4>{product.title}</h4>
        <strong>{money(product.price_minor)}</strong>
        {product.stretch && (
          <span
            className="stretch-badge"
            title="A strong match priced above this piece's share of your budget; it still fits your total."
          >
            Above this piece's budget
          </span>
        )}
        {sellerText[label] && (
          <span className={`seller-badge ${label}`} title={product.seller_note || undefined}>
            {label === 'verified_small_business' ? <BadgeCheck size={12} /> : <Store size={12} />}
            {sellerText[label]}
          </span>
        )}
        {product.rating != null && (
          <span className="rating">
            <Star size={12} /> {product.rating.toFixed(1)}
            {product.rating_count ? ` (${product.rating_count})` : ''}
          </span>
        )}
        {product.match_reason && product.source !== 'seed' && (
          <p className="match-reason">{product.match_reason}</p>
        )}
        <p className="fine-print">
          {product.price_source === 'user'
            ? 'Price as you entered it'
            : product.price_fetched_at
              ? `Price from store page · ${new Date(product.price_fetched_at).toLocaleDateString()}`
              : 'Illustrative price'}
          {product.availability === 'in_stock' ? ' · In stock' : ''}
        </p>
        {onChoose && (
          <button className="small" onClick={onChoose} disabled={disabled}>
            <Check size={14} /> Choose
          </button>
        )}
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer">
            View at store <ExternalLink size={11} />
          </a>
        )}
      </div>
    </article>
  )
}

function Review({ look, onRefine }: { look: Look; onRefine: (prompt: string) => void }) {
  const chosen = look.items.filter((item) => item.status === 'locked' && item.chosen_product)
  return (
    <section className="panel review-panel stack compact">
      <span className="eyebrow">STEP 6 · YOUR COMPLETE LOOK</span>
      <h3>Ready to shop</h3>
      {look.styling_note && look.styling_note !== 'Styling note placeholder.' && (
        <p className="styling-note">{look.styling_note}</p>
      )}
      <ul className="review-list">
        {chosen.map((item) => (
          <li key={item.id}>
            <span className="capitalize">{item.category}</span>
            <a
              href={safeWebUrl(item.chosen_product!.url ?? undefined)}
              target="_blank"
              rel="noopener noreferrer"
            >
              {item.chosen_product!.title} · {item.chosen_product!.retailer} ↗
            </a>
            <strong>{money(item.chosen_product!.price_minor)}</strong>
          </li>
        ))}
        {look.items
          .filter((item) => item.status === 'owned')
          .map((item) => (
            <li key={item.id} className="muted">
              <span className="capitalize">{item.category}</span>
              <span>From your wardrobe</span>
              <strong>{money(0)}</strong>
            </li>
          ))}
      </ul>
      <div className="summary-row">
        <span>Total</span>
        <strong>{money(look.total_spent_minor)}</strong>
      </div>
      <div className="summary-row">
        <span>Remaining budget</span>
        <strong>{money(look.remaining_budget_minor)}</strong>
      </div>
      <button
        type="button"
        className="secondary"
        onClick={() => onRefine('I want to update this look while keeping the pieces I selected.')}
      >
        <SlidersHorizontal size={14} /> Update this look
      </button>
      <p className="fine-print">Refine the full look or swap one piece without starting over.</p>
    </section>
  )
}
