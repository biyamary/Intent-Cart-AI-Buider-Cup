import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, post } from '../lib/api'
import { categories, money, type Category, type ChecklistItem, type Look } from '../lib/types'
import { useLookStore } from '../store/lookStore'
import { PageTitle, ErrorMessage } from '../components/Feedback'
import { LookSummary } from '../components/LookSummary'
import { ProductCard } from '../components/ProductCard'

function Checklist({ look, onChange }: { look: Look; onChange: (look: Look) => void }) {
  const [choices, setChoices] = useState<Record<Category, 'open' | 'owned' | 'removed'>>(
    () =>
      Object.fromEntries(
        categories.map((category) => [
          category,
          look.items.some((i) => i.category === category) ? 'open' : 'removed',
        ]),
      ) as Record<Category, 'open' | 'owned' | 'removed'>,
  )
  const confirm = useMutation({
    mutationFn: () =>
      post<Look>(`/clothes/looks/${look.id}/checklist`, {
        confirmed: true,
        items: categories.map((category) => ({ category, status: choices[category] })),
      }),
    onSuccess: onChange,
  })
  return (
    <form
      className="panel stack"
      onSubmit={(e) => {
        e.preventDefault()
        confirm.mutate()
      }}
    >
      <div>
        <span className="eyebrow">02 / Make it your checklist</span>
        <h2>The pieces of your look.</h2>
        <p>Choose what to find, what you already own, and what to skip.</p>
      </div>
      {categories.map((category) => (
        <label className="checklist-row" key={category}>
          <span className="capitalize">{category}</span>
          <select
            value={choices[category]}
            onChange={(e) =>
              setChoices({ ...choices, [category]: e.target.value as 'open' | 'owned' | 'removed' })
            }
          >
            <option value="open">Find for me</option>
            <option value="owned">Already own</option>
            <option value="removed">Skip this</option>
          </select>
        </label>
      ))}
      <ErrorMessage error={confirm.error} />
      <button disabled={confirm.isPending}>
        {confirm.isPending ? 'Finding sample pieces…' : 'Confirm checklist & find pieces →'}
      </button>
    </form>
  )
}

function ShoppingItem({
  item,
  disabled,
  act,
}: {
  item: ChecklistItem
  disabled: boolean
  act: (id: string, action: string, product_id?: string) => void
}) {
  return (
    <section className={`panel stack ${item.status === 'removed' ? 'subdued' : ''}`}>
      <div className="section-heading">
        <div>
          <span className="eyebrow">
            {item.status === 'locked'
              ? 'SELECTED'
              : item.status === 'owned'
                ? 'ALREADY IN YOUR WARDROBE'
                : item.status === 'removed'
                  ? 'SKIPPED'
                  : `UP TO ${money(item.budget_cap_minor)}`}
          </span>
          <h3 className="capitalize">{item.category}</h3>
        </div>
        <div className="item-actions">
          {item.status === 'open' ? (
            <>
              <button
                className="text-button"
                disabled={disabled}
                onClick={() => act(item.id, 'own')}
              >
                I own this
              </button>
              <button
                className="text-button"
                disabled={disabled}
                onClick={() => act(item.id, 'remove')}
              >
                Skip
              </button>
            </>
          ) : (
            <button
              className="text-button"
              disabled={disabled}
              onClick={() => act(item.id, item.status === 'locked' ? 'swap' : 'reopen')}
            >
              {item.status === 'locked' ? 'Swap item' : 'Find options'}
            </button>
          )}
        </div>
      </div>
      {item.chosen_product && <ProductCard product={item.chosen_product} />}
      {item.status === 'open' &&
        (item.candidates.length ? (
          <div className="product-grid">
            {item.candidates.map((product) => (
              <ProductCard
                key={product.id}
                product={product}
                disabled={disabled}
                onChoose={() => act(item.id, 'lock', product.id)}
              />
            ))}
          </div>
        ) : (
          <div className="notice">
            No sample products fit this category's current budget. Skip it, mark it owned, or free
            budget by swapping a selected item.
          </div>
        ))}
    </section>
  )
}

export function LookBoard() {
  const { look, setLook } = useLookStore()
  const [occasion, setOccasion] = useState('')
  const [description, setDescription] = useState('')
  const [budget, setBudget] = useState('6000')
  const [eventDate, setEventDate] = useState('')
  const history = useQuery({ queryKey: ['looks'], queryFn: () => api<Look[]>('/clothes/looks') })
  const accept = (value: Look) => {
    setLook(value)
    void history.refetch()
  }
  const create = useMutation({
    mutationFn: () =>
      post<Look>('/clothes/looks', {
        occasion,
        description,
        total_budget_minor: Math.round(Number(budget) * 100),
        event_date: eventDate || null,
      }),
    onSuccess: accept,
  })
  const action = useMutation({
    mutationFn: ({ id, action, product_id }: { id: string; action: string; product_id?: string }) =>
      post<Look>(`/clothes/looks/${look!.id}/items/${id}`, { action, product_id }),
    onSuccess: accept,
  })
  const assemble = useMutation({
    mutationFn: () => post<Look>(`/clothes/looks/${look!.id}/assemble`),
    onSuccess: accept,
  })
  const busy = action.isPending || assemble.isPending
  return (
    <>
      <PageTitle
        eyebrow="THE STYLE COMPANION"
        title="A whole look. All you."
        description="Tell us the occasion. Pick your pieces. Keep every choice within the budget you set."
      />
      {!look ? (
        <div className="workspace">
          <form
            className="panel stack"
            onSubmit={(e) => {
              e.preventDefault()
              create.mutate()
            }}
          >
            <div>
              <span className="eyebrow">01 / The brief</span>
              <h2>What are you dressing for?</h2>
            </div>
            <label>
              Occasion
              <input
                required
                maxLength={200}
                value={occasion}
                onChange={(e) => setOccasion(e.target.value)}
                placeholder="e.g. A friend's mehendi"
              />
            </label>
            <label>
              The look you have in mind
              <textarea
                rows={4}
                maxLength={2000}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Colours, mood, comfort, anything that feels like you…"
              />
            </label>
            <div className="two-columns">
              <label>
                Total budget · INR
                <input
                  type="number"
                  required
                  min="1"
                  max="1000000"
                  step="0.01"
                  value={budget}
                  onChange={(e) => setBudget(e.target.value)}
                />
              </label>
              <label>
                Event date · optional
                <input
                  type="date"
                  value={eventDate}
                  onChange={(e) => setEventDate(e.target.value)}
                />
              </label>
            </div>
            <p className="fine-print">
              This demo proposes a starter checklist and uses sample products. Reference-image
              interpretation and live discovery are integration placeholders.
            </p>
            <ErrorMessage error={create.error} />
            <button disabled={create.isPending || !occasion.trim()}>
              {create.isPending ? 'Preparing checklist…' : 'Build my checklist →'}
            </button>
          </form>
          <aside className="stack">
            <section className="panel tinted">
              <h3>
                Less searching.
                <br />
                More coming together.
              </h3>
              <p>
                Keep the pieces you love. Swap the ones you don't. Your remaining budget updates
                with every choice.
              </p>
            </section>
            <section className="panel">
              <h3>Recent looks</h3>
              <ErrorMessage error={history.error} />
              {history.data?.length ? (
                <div className="history-list">
                  {[...history.data].reverse().map((item) => (
                    <button className="history-item" key={item.id} onClick={() => setLook(item)}>
                      <strong>{item.brief.occasion}</strong>
                      <span>{money(item.brief.total_budget_minor ?? 0)} · Open look ↗</span>
                    </button>
                  ))}
                </div>
              ) : (
                <p>Your looks will appear here.</p>
              )}
            </section>
          </aside>
        </div>
      ) : (
        <>
          <button
            className="text-button back"
            disabled={busy}
            onClick={() => {
              setLook(null)
              action.reset()
              assemble.reset()
              create.reset()
            }}
          >
            ← Start another look
          </button>
          <div className="workspace">
            <div className="stack">
              <ErrorMessage error={action.error || assemble.error} />
              {look.status === 'awaiting_checklist' ? (
                <Checklist key={look.id} look={look} onChange={accept} />
              ) : (
                <>
                  {look.items.map((item) => (
                    <ShoppingItem
                      key={item.id}
                      item={item}
                      disabled={busy}
                      act={(id, action, product_id) => {
                        assemble.reset()
                        actionMutation(id, action, product_id)
                      }}
                    />
                  ))}
                  <button
                    disabled={
                      busy ||
                      look.status === 'assembled' ||
                      look.items.some((i) => i.status === 'open') ||
                      look.items.every((i) => i.status === 'removed')
                    }
                    onClick={() => assemble.mutate()}
                  >
                    {assemble.isPending
                      ? 'Assembling…'
                      : look.status === 'assembled'
                        ? 'Look assembled ✓'
                        : 'Assemble my look →'}
                  </button>
                </>
              )}
            </div>
            <LookSummary look={look} />
          </div>
        </>
      )}
    </>
  )
  function actionMutation(id: string, verb: string, product_id?: string) {
    action.mutate({ id, action: verb, product_id })
  }
}
