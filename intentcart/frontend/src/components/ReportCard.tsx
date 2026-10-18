import type { FoodReport } from '../lib/types'

export function ReportCard({ report }: { report: FoodReport }) {
  const regions = [...new Set(report.regulatory_alerts.map((row) => row.country))]
  const ingredients = [...new Set(report.regulatory_alerts.map((row) => row.ingredient))]
  const verified = report.regulatory_alerts.filter((row) => row.verified).length
  const savedAllergies = report.profile_context?.allergies
  const labelAllergens = report.label_allergens ?? []
  return (
    <article className="panel stack">
      <div>
        <span className="eyebrow">03 / Your label review</span>
        <h2>{report.product.name}</h2>
        <p>{report.summary}</p>
      </div>
      {(verified < report.regulatory_alerts.length || report.research?.failure_reason) && (
        <div className="notice amber" role="status">
          <strong>Evidence incomplete</strong>
          <p>
            {verified} of {report.regulatory_alerts.length} ingredient-country comparisons have
            supporting evidence. Unverified means evidence is missing; it does not mean banned or
            permitted.
          </p>
          {report.research?.message && <p>{report.research.message}</p>}
          {report.research && (
            <p className="fine-print">
              New research: {report.research.attempted} gaps requested, {report.research.verified}{' '}
              verified. Previously verified evidence reused: {report.research.cache_hits}. Gaps not
              researched: {report.research.deferred}.
            </p>
          )}
        </div>
      )}
      <section>
        <h3>
          Possible allergy matches <span className="count">{report.allergy_alerts.length}</span>
        </h3>
        {report.allergy_alerts.length ? (
          <div className="stack compact">
            {report.allergy_alerts.map((alert, i) => (
              <div className="notice amber" key={i}>
                <strong>{alert.allergen}</strong> ·{' '}
                {alert.type === 'may_contain' ? 'May contain' : 'Label match'}:{' '}
                {alert.matched_ingredient}
              </div>
            ))}
          </div>
        ) : savedAllergies?.length === 0 ? (
          <p>
            No allergies are saved in your profile, so personal allergy matching was not performed.
          </p>
        ) : (
          <p>No label matches in the current dictionary. This does not rule out allergens.</p>
        )}
        {labelAllergens.length > 0 && (
          <div>
            <h4>Allergen terms found on the label</h4>
            <ul>
              {(['contains', 'may_contain'] as const).map((kind) => {
                const names = [
                  ...new Set(labelAllergens.filter((a) => a.type === kind).map((a) => a.allergen)),
                ]
                return names.length ? (
                  <li key={kind}>
                    {kind === 'contains'
                      ? 'Ingredient / contains statement'
                      : 'May contain statement'}
                    : {names.join(', ')}
                  </li>
                ) : null
              })}
            </ul>
            <p className="fine-print">
              Dictionary matches only. Check the full allergen statement on the packaging.
            </p>
          </div>
        )}
      </section>
      <section>
        <h3>Ingredients and purpose</h3>
        <div className="stack compact">
          {report.ingredients.map((ingredient) => (
            <div key={ingredient.canonical}>
              <strong>{ingredient.canonical}</strong>
              {ingredient.additive_id && ` (${ingredient.additive_id})`}
              <p>
                {ingredient.role} — {ingredient.explanation}
              </p>
              {ingredient.source_url && (
                <a href={ingredient.source_url} target="_blank" rel="noreferrer">
                  Purpose source
                </a>
              )}
              {ingredient.purpose_basis === 'label' && (
                <span className="fine-print">Function from your confirmed label</span>
              )}
              <details>
                <summary>Original label entry</summary>
                <p>{ingredient.raw}</p>
              </details>
              {ingredient.iarc && (
                <div className="notice amber">
                  <strong>
                    IARC Group {ingredient.iarc.group}: {ingredient.iarc.label}
                  </strong>
                  <p>{ingredient.iarc.context}</p>
                  <a href={ingredient.iarc.source_url} target="_blank" rel="noreferrer">
                    IARC source · evaluation {ingredient.iarc.evaluated_year}
                  </a>
                </div>
              )}
            </div>
          ))}
        </div>
      </section>
      <section>
        <h3>Country comparison</h3>
        <p className="fine-print">
          Restrictions depend on the food category, quantity, territory and date. Citation matched
          means the passage was found, not that its legal interpretation was reviewed.
        </p>
        {report.regulatory_alerts.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Ingredient</th>
                  {regions.map((region) => (
                    <th scope="col" key={region}>
                      {region}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ingredients.map((ingredient) => (
                  <tr key={ingredient}>
                    <th scope="row">{ingredient}</th>
                    {regions.map((region) => {
                      const alert = report.regulatory_alerts.find(
                        (row) => row.ingredient === ingredient && row.country === region,
                      )
                      return (
                        <td key={region}>
                          <strong>{alert?.verified ? alert.status : 'unverified'}</strong>
                          {alert?.verified && <p>{alert.condition}</p>}
                          {alert?.verified && alert.source_url && (
                            <>
                              <a href={alert.source_url} target="_blank" rel="noreferrer">
                                Source
                              </a>
                              <p className="fine-print">
                                {alert.verification === 'citation_verified'
                                  ? 'Citation matched'
                                  : 'Reviewed entry'}
                                {alert.checked_at ? ` · ${alert.checked_at.slice(0, 10)}` : ''}
                              </p>
                              {alert.quote_or_snippet && (
                                <details>
                                  <summary>Evidence passage</summary>
                                  <p>{alert.quote_or_snippet}</p>
                                </details>
                              )}
                            </>
                          )}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No regulatory findings are available.</p>
        )}
      </section>
      <section>
        <h3>Profile checks</h3>
        {report.profile_context?.diet?.length === 0 && (
          <p>No dietary preferences are saved, so personal diet matching was not performed.</p>
        )}
        {report.diet_conflicts.map((item, index) => (
          <p key={`diet-${index}`}>
            {item.diet}: {item.note}
          </p>
        ))}
        {report.age_notes.map((item, index) => (
          <p key={`age-${index}`}>
            {item.age_group}: {item.note}
            {item.source_url && (
              <>
                {' '}
                <a href={item.source_url} target="_blank" rel="noreferrer">
                  Source
                </a>
              </>
            )}
          </p>
        ))}
      </section>
      <section>
        <h3>What needs a closer look</h3>
        <ul className="notes">
          {report.things_to_watch.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>
      <p className="fine-print">{report.disclaimer}</p>
    </article>
  )
}
