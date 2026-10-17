import { create } from 'zustand'
import type { Look } from '../lib/types'

// Server is authoritative for budgets and chosen products. No duplicated client arithmetic.
export const useLookStore = create<{ look: Look | null; setLook: (look: Look | null) => void }>(
  (set) => ({
    look: null,
    setLook: (look) => set({ look }),
  }),
)
