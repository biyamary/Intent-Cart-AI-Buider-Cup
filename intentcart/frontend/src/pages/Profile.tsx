import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../lib/api'
import { commaList, countries, type Country, type Profile as ProfileData } from '../lib/types'
import { PageTitle, ErrorMessage } from '../components/Feedback'

function ProfileForm({ profile }: { profile: ProfileData }) {
  const cache = useQueryClient()
  const [country, setCountry] = useState(profile.country)
  const [foodCountries, setFoodCountries] = useState<Country[]>(profile.food_countries ?? [])
  const [age, setAge] = useState(profile.age_group)
  const [allergies, setAllergies] = useState(profile.allergies.join(', '))
  const [diet, setDiet] = useState(profile.diet.join(', '))
  const [colours, setColours] = useState(profile.style.colours.join(', '))
  const [platforms, setPlatforms] = useState(profile.style.preferred_platforms.join(', '))
  const [sizes, setSizes] = useState(profile.style.sizes.clothing ?? '')
  const [budgetBand, setBudgetBand] = useState(profile.style.budget_band)
  const save = useMutation({
    mutationFn: () =>
      api<ProfileData>('/profile', {
        method: 'PUT',
        body: JSON.stringify({
          country,
          food_countries: foodCountries,
          age_group: age,
          allergies: commaList(allergies),
          diet: commaList(diet),
          style: {
            ...profile.style,
            colours: commaList(colours),
            preferred_platforms: commaList(platforms),
            sizes: { ...profile.style.sizes, clothing: sizes },
            budget_band: budgetBand,
          },
        }),
      }),
    onSuccess: (value) => cache.setQueryData(['profile'], value),
  })
  return (
    <form
      className="panel stack"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
      onChange={() => {
        if (save.isSuccess) save.reset()
      }}
    >
      <div>
        <span className="eyebrow">THE EVERYDAY ESSENTIALS</span>
        <h2>Make it personal.</h2>
      </div>
      <div className="two-columns">
        <label>
          Country
          <select value={country} onChange={(e) => setCountry(e.target.value as Country)}>
            {countries.map((c) => (
              <option key={c}>{c}</option>
            ))}
          </select>
        </label>
        <label>
          Age group
          <select value={age} onChange={(e) => setAge(e.target.value as ProfileData['age_group'])}>
            <option value="unspecified">Prefer not to say</option>
            <option value="child">Child</option>
            <option value="teen">Teen</option>
            <option value="adult">Adult</option>
          </select>
        </label>
      </div>
      <label>
        Allergies · comma separated
        <input
          value={allergies}
          onChange={(e) => setAllergies(e.target.value)}
          placeholder="e.g. milk, peanut, wheat"
        />
      </label>
      <label>
        Dietary preferences
        <input
          value={diet}
          onChange={(e) => setDiet(e.target.value)}
          placeholder="e.g. vegetarian"
        />
      </label>
      <fieldset>
        <legend>Food comparison countries</legend>
        <p className="fine-print">Leave blank to use EU, UK, India, US and your country.</p>
        <div className="chips">
          {countries.map((region) => (
            <label className="check-chip" key={region}>
              <input
                type="checkbox"
                checked={foodCountries.includes(region)}
                onChange={(e) =>
                  setFoodCountries(
                    e.target.checked
                      ? [...foodCountries, region]
                      : foodCountries.filter((c) => c !== region),
                  )
                }
              />
              {region}
            </label>
          ))}
        </div>
      </fieldset>
      <hr />
      <h3>Your style preferences</h3>
      <div className="two-columns">
        <label>
          Favourite colours
          <input
            value={colours}
            onChange={(e) => setColours(e.target.value)}
            placeholder="e.g. sage, ivory"
          />
        </label>
        <label>
          Clothing size
          <input value={sizes} onChange={(e) => setSizes(e.target.value)} placeholder="e.g. M" />
        </label>
      </div>
      <label>
        Preferred shopping platforms
        <input
          value={platforms}
          onChange={(e) => setPlatforms(e.target.value)}
          placeholder="Separate with commas"
        />
      </label>
      <label>
        Usual budget band
        <input
          value={budgetBand}
          onChange={(e) => setBudgetBand(e.target.value)}
          placeholder="e.g. ₹3,000–₹6,000"
        />
      </label>
      <p className="fine-print">
        Food reviews use your saved allergies, diet, age group and comparison countries. Analyze a
        confirmed label again after changing these preferences.
      </p>
      <ErrorMessage error={save.error} />
      {save.isSuccess && (
        <div className="notice success" role="status">
          Preferences saved.
        </div>
      )}
      <button disabled={save.isPending}>
        {save.isPending ? 'Saving…' : 'Save my preferences'}
      </button>
    </form>
  )
}

export function Profile() {
  const query = useQuery({ queryKey: ['profile'], queryFn: () => api<ProfileData>('/profile') })
  return (
    <>
      <PageTitle
        eyebrow="YOUR PROFILE"
        title="Good to know you."
        description="A few preferences to make your shopping companion more useful."
      />
      <div className="workspace">
        <div>
          {query.isPending && <div className="panel">Loading your preferences…</div>}
          <ErrorMessage error={query.error} />
          {query.data && <ProfileForm profile={query.data} />}
        </div>
        <aside className="panel tinted">
          <h3>
            One profile.
            <br />
            Both companions.
          </h3>
          <p>
            Your profile is available to both flows. You can update it whenever your preferences
            change.
          </p>
          <p className="fine-print">
            In local demo mode, everyone uses one demo profile. Data is held in memory and resets
            when the API restarts.
          </p>
        </aside>
      </div>
    </>
  )
}
