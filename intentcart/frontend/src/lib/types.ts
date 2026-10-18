export const countries = [
  'EU',
  'UK',
  'India',
  'US',
  'Canada',
  'Australia/NZ',
  'Japan',
  'UAE',
] as const
export type Country = (typeof countries)[number]
export const categories = [
  'outfit',
  'earrings',
  'necklace',
  'bangles',
  'footwear',
  'handbag',
  'hair accessories',
] as const
export type Category = (typeof categories)[number]
export interface Profile {
  country: Country
  food_countries?: Country[]
  age_group: 'unspecified' | 'child' | 'teen' | 'adult'
  allergies: string[]
  diet: string[]
  style: {
    sizes: Record<string, string>
    colours: string[]
    budget_band: string
    preferred_platforms: string[]
  }
}
export interface FoodReport {
  product: { name: string; source: string; barcode: string | null; source_url: string | null }
  ingredients: {
    raw: string
    canonical: string
    role: string
    explanation: string
    additive_id?: string | null
    source_url?: string | null
    purpose_basis?: 'reviewed' | 'label' | 'citation_verified' | 'unverified'
    iarc?: {
      group: string
      label: string
      context: string
      source_url: string
      evaluated_year: number
    } | null
  }[]
  allergy_alerts: {
    allergen: string
    matched_ingredient: string
    type: 'contains' | 'may_contain'
  }[]
  label_allergens?: FoodReport['allergy_alerts']
  profile_context?: Pick<Profile, 'allergies' | 'diet' | 'age_group'>
  research?: {
    status: 'not_needed' | 'disabled' | 'completed' | 'partial' | 'unavailable'
    total_gaps: number
    cache_hits: number
    attempted: number
    verified: number
    deferred: number
    failure_reason: string | null
    message: string
  }
  regulatory_alerts: {
    ingredient: string
    country: Country
    status: string
    condition: string
    source_url: string | null
    verified: boolean
    verification?: 'reviewed' | 'citation_verified' | 'unverified'
    quote_or_snippet?: string
    checked_at?: string | null
  }[]
  diet_conflicts: Record<string, string>[]
  age_notes: Record<string, string>[]
  things_to_watch: string[]
  summary: string
  disclaimer: string
  generated_at: string
}
export interface Scan {
  id: string
  product: FoodReport['product']
  ingredients: string[]
  contains: string[]
  may_contain: string[]
  status: 'awaiting_confirmation' | 'reported'
  report: FoodReport | null
  created_at: string
}
export interface Product {
  id: string
  category: Category
  title: string
  price_minor: number
  currency: string
  retailer: string
  url: string | null
  image_url: string | null
  colour: string
  source: 'seed' | 'live'
  price_fetched_at: string | null
  match_reason: string
}
export interface ChecklistItem {
  id: string
  category: Category
  status: 'open' | 'locked' | 'owned' | 'removed'
  budget_cap_minor: number
  chosen_product: Product | null
  candidates: Product[]
}
export interface Look {
  id: string
  brief: {
    occasion: string
    description: string
    total_budget_minor: number
    currency: string
    event_date: string | null
  }
  status: 'awaiting_checklist' | 'shopping' | 'assembled'
  items: ChecklistItem[]
  total_spent_minor: number
  remaining_budget_minor: number
  styling_note: string
  created_at: string
}
export const money = (minor: number) =>
  new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(minor / 100)
export const commaList = (value: string) =>
  value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
