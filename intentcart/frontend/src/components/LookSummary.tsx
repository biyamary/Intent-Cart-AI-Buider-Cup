import { money, type Look } from '../lib/types'

export function LookSummary({ look }: { look: Look }) {
  const resolved = look.items.filter((i) => i.status !== 'open' && i.status !== 'removed').length
  const total = look.items.filter((i) => i.status !== 'removed').length
  return (
    <aside className="panel summary stack">
      <span className="eyebrow">Your look, at a glance</span>
      <h2>{look.brief.occasion}</h2>
      <div className="budget-number">{money(look.remaining_budget_minor)}</div>
      <p>left of your {money(look.brief.total_budget_minor)} budget</p>
      <div className="budget-track">
        <div
          style={{ width: `${(look.total_spent_minor / look.brief.total_budget_minor) * 100}%` }}
        />
      </div>
      <div className="summary-row">
        <span>Selected items</span>
        <strong>{money(look.total_spent_minor)}</strong>
      </div>
      <div className="summary-row">
        <span>Checklist progress</span>
        <strong>
          {resolved} / {total}
        </strong>
      </div>
      <hr />
      <p className="fine-print">
        Sample catalog prices are for demonstration. Owned items use none of your shopping budget.
      </p>
      {look.status === 'assembled' && (
        <div className="notice">
          <strong>Your look is ready.</strong>
          <p>{look.styling_note}</p>
        </div>
      )}
    </aside>
  )
}
