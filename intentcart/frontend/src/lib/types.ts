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
export type KnownCategory = (typeof categories)[number]
// Stylist looks may add custom items such as 'dupatta'.
export type Category = string
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
export type SellerLabel =
  'verified_small_business' | 'independent' | 'marketplace' | 'brand' | 'unknown'
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
  source: 'seed' | 'live' | 'user'
  price_fetched_at: string | null
  match_reason: string
  price_source?: 'catalog' | 'page' | 'user'
  verification?: 'seed' | 'json_ld' | 'shopify' | 'open_graph' | 'microdata' | 'page_html' | 'user'
  availability?: 'in_stock' | 'out_of_stock' | 'unknown'
  rating?: number | null
  rating_count?: number | null
  seller_label?: SellerLabel
  seller_note?: string
  style_score?: number | null
  stretch?: boolean
}
export type FeedbackReason =
  | 'too_expensive'
  | 'wrong_colour'
  | 'too_heavy'
  | 'too_plain'
  | 'not_my_style'
  | 'poor_quality_look'
  | 'wrong_item'
  | 'love_colour'
  | 'love_design'
  | 'good_price'
export interface ProductFeedback {
  product_id: string
  title: string
  sentiment: 'like' | 'dislike'
  reasons: FeedbackReason[]
  note: string
}
export interface Boutique {
  name: string
  url: string | null
  note: string
  kind: 'local' | 'online'
}
export type DiscoveryStatus = 'idle' | 'searching' | 'ready' | 'no_results' | 'failed'
export type RetailerPolicy = 'popular_first' | 'balanced' | 'independent_first' | 'independent_only'
export interface PriceBand {
  low_minor: number
  typical_minor: number
  high_minor: number
  sample_count: number
  source: 'fallback' | 'market' | 'selected'
}
export interface BudgetPlan {
  revision: number
  status: 'estimating' | 'surveying' | 'ready' | 'infeasible'
  feasible: boolean | null
  minimum_complete_total_minor: number
  planned_total_minor: number
  verified_item_count: number
  open_item_count: number
  note: string
}
export interface ChecklistItem {
  id: string
  category: Category
  status: 'open' | 'locked' | 'owned' | 'removed'
  budget_cap_minor: number
  chosen_product: Product | null
  candidates: Product[]
  target?: string
  hints?: string[]
  discovery?: DiscoveryStatus
  discovery_note?: string
  boutiques?: Boutique[]
  budget_role?: string
  price_band?: PriceBand
  planned_budget_minor?: number
  reserved_product_id?: string | null
  survey_status?: 'pending' | 'surveying' | 'ready' | 'no_verified_prices' | 'not_needed'
  feedback?: ProductFeedback[]
}
export interface InspirationItem {
  id: string
  kind: 'pinterest' | 'web'
  url: string
  title: string
  image_url: string | null
  source: string
}
export interface ConceptImage {
  id: string
  artifact: string
  kind: 'concept' | 'reference_edit' | 'final'
  caption: string
  created_at: string
}
export interface LookAnalysis {
  summary: string
  occasion: string
  palette: string[]
  style_tags: string[]
}
export interface Look {
  id: string
  brief: {
    occasion: string
    description: string
    /** null while an agent look is still in the ideas stage. */
    total_budget_minor: number | null
    currency: string
    event_date: string | null
    sizes?: string
    colours?: string[]
    avoid_colours?: string[]
    platforms?: string[]
    delivery_city?: string
    delivery_pin?: string
    small_business?: 'off' | 'prefer' | 'only'
    retailer_policy?: RetailerPolicy
  }
  status: 'exploring' | 'awaiting_checklist' | 'shopping' | 'assembled'
  items: ChecklistItem[]
  total_spent_minor: number
  remaining_budget_minor: number
  styling_note: string
  created_at: string
  mode?: 'board' | 'agent'
  session_id?: string | null
  analysis?: LookAnalysis | null
  references?: string[]
  inspiration?: InspirationItem[]
  concepts?: ConceptImage[]
  revision?: number
  budget_plan?: BudgetPlan
  plan_revision?: number
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
