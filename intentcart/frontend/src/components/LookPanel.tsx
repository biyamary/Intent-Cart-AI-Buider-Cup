import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  BadgeCheck,
  Check,
  ExternalLink,
  Link2,
  Loader2,
  MapPin,
  Plus,
  RefreshCw,
  Shirt,
  Sparkles,
  Star,
  Store,
  TrendingDown,
  X,
} from 'lucide-react'
import { api, post } from '../lib/api'
import { money, type ChecklistItem, type Look, type Product, type SellerLabel } from '../lib/types'
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
  return Boolean(look?.items.some((item) => item.discovery === 'searching'))
}

export function LookPanel({ lookId, sessionId }: { lookId: string; sessionId: string }) {
  const cache = useQueryClient()
  const path = `/clothes/looks/${lookId}`
  const look = useQuery({
    queryKey: ['look', lookId],
    queryFn: () => api<Look>(path),
    refetchInterval: (query) => (isSearching(query.state.data) ? 2500 : false),
  })
  const update = useMutation({
    mutationFn: ({ url, body }: { url: string; body?: unknown }) => post<Look>(url, body),
    onSuccess: (data) => cache.setQueryData(['look', lookId], data),
  })
  const act = (url: string, body?: unknown) => update.mutate({ url: `${path}${url}`, body })
  const data = look.data
  if (look.isPending) return <aside className="panel look-panel">Loading your look board…</aside>
  if (!data)
    return (
      <aside className="panel look-panel">
        <ErrorMessage error={look.error} />
      </aside>
    )
  const busy = update.isPending
  const spentShare = Math.min(100, (data.total_spent_minor / data.brief.total_budget_minor) * 100)
  const open = data.items.filter((item) => item.status === 'open')
  return (
    <aside className="look-panel stack" aria-label="Look board">
      <section className="panel summary look-header">
        <div className="look-header-top">
          <div>
            <span className="eyebrow">YOUR LOOK BOARD</span>
            <h2>{data.brief.occasion}</h2>
          </div>
          {data.brief.small_business && data.brief.small_business !== 'off' && (
            <span className="seller-badge independent">
              <Store size={12} />
              {data.brief.small_business === 'only'
                ? 'Small businesses only'
                : 'Favouring small businesses'}
            </span>
          )}
        </div>
        <div className="budget-number">{money(data.remaining_budget_minor)}</div>
        <p>left of {money(data.brief.total_budget_minor)}</p>
        <div className="budget-track">
          <div style={{ width: `${spentShare}%` }} />
        </div>
        <div className="summary-row">
          <span>Selected</span>
          <strong>{money(data.total_spent_minor)}</strong>
        </div>
        {data.analysis?.palette?.length ? (
          <div className="palette-row" aria-label="Palette">
            {data.analysis.palette.map((colour) => (
              <span key={colour}>{colour}</span>
            ))}
          </div>
        ) : null}
      </section>
      <ErrorMessage error={update.error} />
      <Inspiration look={data} sessionId={sessionId} />
      {data.status === 'awaiting_checklist' ? (
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
          {data.status === 'assembled' && <Review look={data} />}
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

function Inspiration({ look, sessionId }: { look: Look; sessionId: string }) {
  const concepts = look.concepts ?? []
  const pins = (look.inspiration ?? []).filter((i) => i.kind === 'pinterest')
  const pages = (look.inspiration ?? []).filter((i) => i.kind === 'web' && i.image_url)
  if (!concepts.length && !pins.length && !pages.length) return null
  return (
    <section className="panel inspiration-panel">
      <span className="eyebrow">
        <Sparkles size={12} /> INSPIRATION
      </span>
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
        {pages.map((page) => (
          <a
            key={page.id}
            className="concept-card"
            href={safeWebUrl(page.url)}
            target="_blank"
            rel="noopener noreferrer"
          >
            <RemoteImage src={page.image_url!} alt={page.title} />
            <span className="figcaption">
              {page.title} · {page.source} ↗
            </span>
          </a>
        ))}
        {pins.map((pin) => (
          <PinterestPin key={pin.id} url={pin.url} title={pin.title} />
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
                  onChoose={() => act(itemPath, { action: 'lock', product_id: product.id })}
                  onReject={() => act(itemPath, { action: 'reject', product_id: product.id })}
                />
              ))}
            </div>
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

export function LiveProductCard({
  product,
  onChoose,
  onReject,
  disabled,
  compact,
}: {
  product: Product
  onChoose?: () => void
  onReject?: () => void
  disabled?: boolean
  compact?: boolean
}) {
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
        {onReject && (
          <button
            className="reject-button"
            aria-label={`Hide ${product.title}`}
            title="Not for me"
            disabled={disabled}
            onClick={onReject}
          >
            <X size={14} />
          </button>
        )}
      </div>
      <div className="product-info">
        <span className="eyebrow">{product.retailer}</span>
        <h4>{product.title}</h4>
        <strong>{money(product.price_minor)}</strong>
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

function Review({ look }: { look: Look }) {
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
      <p className="fine-print">Swap any single piece above without rebuilding the look.</p>
    </section>
  )
}
