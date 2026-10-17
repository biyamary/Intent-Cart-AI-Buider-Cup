import type { FoodReport } from '../lib/types'

export function ReportCard({ report }: { report: FoodReport }) {
  return (
    <article className="panel stack">
      <div>
        <span className="eyebrow">03 / Your label review</span>
        <h2>{report.product.name}</h2>
        <p>{report.summary}</p>
      </div>
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
        ) : (
          <p>No matches in the demo dictionary. This does not rule out allergens.</p>
        )}
      </section>
      <section>
        <h3>Regulation sources</h3>
        {report.regulatory_alerts.length ? (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Additive</th>
                  <th>Region</th>
                  <th>Finding</th>
                </tr>
              </thead>
              <tbody>
                {report.regulatory_alerts.map((alert, i) => (
                  <tr key={i}>
                    <td>{alert.ingredient}</td>
                    <td>{alert.country}</td>
                    <td>
                      {alert.verified && alert.source_url ? (
                        <a href={alert.source_url} target="_blank" rel="noreferrer">
                          {alert.status} · source
                        </a>
                      ) : (
                        'Unverified'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p>No E-number matches found. The regulation corpus is not yet populated.</p>
        )}
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
