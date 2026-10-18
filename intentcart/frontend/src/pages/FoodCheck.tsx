import { lazy, Suspense, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MessageSquare, ScanLine } from 'lucide-react'
import { api, post } from '../lib/api'
import type { Scan } from '../lib/types'
import { PageTitle, ErrorMessage } from '../components/Feedback'
import { IngredientEditor } from '../components/IngredientEditor'
import { ReportCard } from '../components/ReportCard'
import { ChatPanel } from '../components/ChatPanel'
const FoodChat = lazy(() =>
  import('../components/FoodChat').then((module) => ({ default: module.FoodChat })),
)
const Scanner = lazy(() =>
  import('../components/Scanner').then((module) => ({ default: module.Scanner })),
)

export function FoodCheck() {
  const cache = useQueryClient()
  const [viewMode, setViewMode] = useState<'chat' | 'scanner'>('chat')
  const [tab, setTab] = useState<'text' | 'barcode' | 'photo'>('text')
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [barcode, setBarcode] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [scan, setScan] = useState<Scan | null>(null)
  const history = useQuery({ queryKey: ['scans'], queryFn: () => api<Scan[]>('/food/scans') })
  const accept = (value: Scan) => {
    setScan(value)
    void cache.invalidateQueries({ queryKey: ['scans'] })
  }
  const extract = useMutation({
    mutationFn: async () => {
      if (tab === 'photo') {
        if (!file) throw new Error('Choose a label photo first.')
        const form = new FormData()
        form.append('image', file)
        return api<Scan>('/food/extract/photo', { method: 'POST', body: form })
      }
      return post<Scan>('/food/extract', {
        source: tab,
        text,
        barcode: tab === 'barcode' ? barcode : null,
        product_name: name || 'Untitled product',
      })
    },
    onSuccess: accept,
  })

  return (
    <>
      {viewMode === 'scanner' && (
        <div className="tabs mode-switch">
          <button type="button" aria-pressed={false} onClick={() => setViewMode('chat')}>
            <MessageSquare size={15} /> Chat with Nia
          </button>
          <button type="button" aria-pressed className="selected">
            <ScanLine size={15} /> Barcode &amp; Photo Scanner
          </button>
        </div>
      )}

      {viewMode === 'chat' ? (
        <Suspense fallback={<p className="chat-loading">Loading your food companion…</p>}>
          <FoodChat onSwitchToScanner={() => setViewMode('scanner')} />
        </Suspense>
      ) : (
        <>
          <PageTitle
            eyebrow="LABEL SCANNER"
            title="Scan or enter your label."
            description="Type, scan barcodes, or upload a photo to generate an instant structured report."
          />
          <div className="workspace">
            <div className="stack">
              {!scan ? (
                <form
                  className="panel stack"
                  onSubmit={(e) => {
                    e.preventDefault()
                    extract.mutate()
                  }}
                >
                  <div>
                    <span className="eyebrow">01 / Add a label</span>
                    <h2>What are we looking at?</h2>
                  </div>
                  <div className="tabs" aria-label="Label input method">
                    {(['text', 'barcode', 'photo'] as const).map((type) => (
                      <button
                        key={type}
                        type="button"
                        aria-pressed={tab === type}
                        className={tab === type ? 'selected' : ''}
                        onClick={() => {
                          setTab(type)
                          extract.reset()
                        }}
                      >
                        {type === 'text'
                          ? 'Type ingredients'
                          : type === 'barcode'
                            ? 'Barcode'
                            : 'Label photo'}
                      </button>
                    ))}
                  </div>
                  <label>
                    Product name <span className="muted">(optional)</span>
                    <input
                      value={name}
                      onChange={(e) => setName(e.target.value)}
                      maxLength={200}
                      placeholder="e.g. Your favourite snack"
                    />
                  </label>
                  {tab === 'text' && (
                    <>
                      <label>
                        Ingredient label
                        <textarea
                          required
                          maxLength={12000}
                          value={text}
                          onChange={(e) => setText(e.target.value)}
                          rows={7}
                          placeholder={
                            'Paste or type the full ingredient list.\nInclude “contains” and “may contain” statements.'
                          }
                        />
                      </label>
                      <button
                        className="text-button"
                        type="button"
                        onClick={() => {
                          setName('Sample snack label')
                          setText(
                            'Ingredients: wheat flour, sugar, milk powder, E102. Contains: milk, wheat. May contain: peanuts.',
                          )
                        }}
                      >
                        Try a sample label
                      </button>
                    </>
                  )}
                  {tab === 'barcode' && (
                    <>
                      <label>
                        Barcode number
                        <input
                          required
                          pattern="[0-9]{8,14}"
                          inputMode="numeric"
                          value={barcode}
                          onChange={(e) => setBarcode(e.target.value)}
                          placeholder="8–14 digits"
                        />
                      </label>
                      <Suspense fallback={<p>Loading camera controls…</p>}>
                        <Scanner onScan={setBarcode} />
                      </Suspense>
                      <p className="fine-print">
                        Barcode lookup requires the Open Food Facts integration. Typed labels work
                        in the local demo.
                      </p>
                    </>
                  )}
                  {tab === 'photo' && (
                    <>
                      <label className="upload-box">
                        Choose a clear photo of the ingredient label
                        <input
                          type="file"
                          accept="image/jpeg,image/png,image/webp"
                          required
                          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                        />
                      </label>
                      <p className="fine-print">
                        JPEG, PNG or WebP · up to 5 MB. Photo extraction requires the Gemini prompt
                        and API configuration.
                      </p>
                    </>
                  )}
                  <ErrorMessage error={extract.error} />
                  <button disabled={extract.isPending}>
                    {extract.isPending ? 'Reading label…' : 'Review ingredients →'}
                  </button>
                </form>
              ) : (
                <>
                  <button
                    className="text-button back"
                    onClick={() => {
                      setScan(null)
                      extract.reset()
                    }}
                  >
                    ← Start another label
                  </button>
                  {scan.status === 'awaiting_confirmation' ? (
                    <IngredientEditor key={scan.id} scan={scan} onComplete={accept} />
                  ) : (
                    scan.report && (
                      <>
                        <ReportCard report={scan.report} />
                        <button
                          className="text-button"
                          onClick={() => setScan({ ...scan, status: 'awaiting_confirmation' })}
                        >
                          Edit ingredients &amp; run review again
                        </button>
                        <ChatPanel key={scan.id} scanId={scan.id} />
                      </>
                    )
                  )}
                </>
              )}
            </div>
            <aside className="stack">
              <section className="panel tinted">
                <span className="eyebrow">A REVIEW THAT KNOWS YOU</span>
                <h3>Your preferences come first.</h3>
                <p>Add your allergies and country to give each label review the right context.</p>
                <Link className="text-link" to="/profile">
                  Edit your profile ↗
                </Link>
              </section>
              <section className="panel">
                <h3>Recent labels</h3>
                {history.isPending && <p>Loading labels…</p>}
                <ErrorMessage error={history.error} />
                {history.data?.length ? (
                  <div className="history-list">
                    {[...history.data].reverse().map((item) => (
                      <button key={item.id} className="history-item" onClick={() => setScan(item)}>
                        <strong>{item.product.name}</strong>
                        <span>
                          {item.status === 'reported' ? 'View report' : 'Confirm ingredients'} ↗
                        </span>
                      </button>
                    ))}
                  </div>
                ) : (
                  history.isSuccess && <p>Your first label review will appear here.</p>
                )}
              </section>
              <p className="fine-print side-note">
                Not medical advice. Always check the original packaging. Missing matches do not mean
                a product is suitable for you.
              </p>
            </aside>
          </div>
        </>
      )}
    </>
  )
}
