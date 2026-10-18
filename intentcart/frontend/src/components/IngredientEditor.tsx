import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, post } from '../lib/api'
import { commaList, countries, type Country, type Profile, type Scan } from '../lib/types'
import { ErrorMessage } from './Feedback'

export function IngredientEditor({
  scan,
  onComplete,
}: {
  scan: Scan
  onComplete: (scan: Scan) => void
}) {
  const [ingredients, setIngredients] = useState(scan.ingredients.join('\n'))
  const [contains, setContains] = useState(scan.contains.join(', '))
  const [traces, setTraces] = useState(scan.may_contain.join(', '))
  const profile = useQuery({ queryKey: ['profile'], queryFn: () => api<Profile>('/profile') })
  const [chosenRegions, setRegions] = useState<Country[] | null>(
    scan.report?.regulatory_alerts.length
      ? [...new Set(scan.report.regulatory_alerts.map((row) => row.country))]
      : null,
  )
  const defaults: Country[] = ['EU', 'UK', 'India', 'US']
  const regions =
    chosenRegions ??
    (profile.data?.food_countries?.length
      ? profile.data.food_countries
      : [...new Set([...defaults, ...(profile.data ? [profile.data.country] : [])])])
  const mutation = useMutation({
    mutationFn: () =>
      post<Scan>(`/food/scans/${scan.id}/analyze`, {
        confirmed: true,
        ingredients: ingredients
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
        contains: commaList(contains),
        may_contain: commaList(traces),
        countries: chosenRegions ?? undefined,
      }),
    onSuccess: onComplete,
  })
  return (
    <form
      className="panel stack"
      onSubmit={(e) => {
        e.preventDefault()
        mutation.mutate()
      }}
    >
      <div>
        <span className="eyebrow">02 / Confirm the label</span>
        <h2>{scan.product.name}</h2>
        <p>Check every entry against the original packaging before continuing.</p>
      </div>
      <label>
        Ingredients · one entry per line
        <textarea
          required
          rows={7}
          value={ingredients}
          onChange={(e) => setIngredients(e.target.value)}
        />
      </label>
      <div className="two-columns">
        <label>
          Contains
          <input
            value={contains}
            onChange={(e) => setContains(e.target.value)}
            placeholder="e.g. milk, wheat"
          />
        </label>
        <label>
          May contain
          <input
            value={traces}
            onChange={(e) => setTraces(e.target.value)}
            placeholder="e.g. peanuts"
          />
        </label>
      </div>
      <fieldset>
        <legend>Countries to check</legend>
        <div className="chips">
          {countries.map((country) => (
            <label className="check-chip" key={country}>
              <input
                type="checkbox"
                checked={regions.includes(country)}
                onChange={(e) =>
                  setRegions(
                    e.target.checked ? [...regions, country] : regions.filter((c) => c !== country),
                  )
                }
              />
              {country}
            </label>
          ))}
        </div>
      </fieldset>
      <ErrorMessage error={mutation.error} />
      <button disabled={mutation.isPending || !regions.length}>
        {mutation.isPending ? 'Reviewing ingredients…' : 'Confirm ingredients & review'}
      </button>
    </form>
  )
}
