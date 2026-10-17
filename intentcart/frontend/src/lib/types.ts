export const countries = ['India', 'EU', 'US', 'UK', 'UAE'] as const
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
  ingredients: { raw: string; canonical: string; role: string; explanation: string }[]
  allergy_alerts: {
    allergen: string
    matched_ingredient: string
    type: 'contains' | 'may_contain'
  }[]
  regulatory_alerts: {
    ingredient: string
    country: Country
    status: string
    condition: string
    source_url: string | null
    verified: boolean
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
