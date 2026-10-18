export type AgentPresentation = {
  id: 'food' | 'stylist'
  name: string
  role: string
  shortRole: string
  route: '/food' | '/clothes'
  description: string
  examplePrompt: string
  capabilities: readonly string[]
}

export const agents = {
  food: {
    id: 'food',
    name: 'Nia',
    role: 'Food Guide',
    shortRole: 'Food',
    route: '/food',
    description:
      'Decode a label, compare ingredients, and understand what works for your preferences.',
    examplePrompt: 'Is this cereal a good everyday option for my family?',
    capabilities: ['Read a label', 'Compare ingredients', 'Check food rules'],
  },
  stylist: {
    id: 'stylist',
    name: 'Mira',
    role: 'Personal Stylist',
    shortRole: 'Style',
    route: '/clothes',
    description:
      'Plan a complete look for your occasion, preferences, and budget, then shop it together.',
    examplePrompt: 'Build me a smart-casual dinner look under ₹4,000.',
    capabilities: ['Plan a look', 'Set the budget', 'Find matching pieces'],
  },
} as const satisfies Record<'food' | 'stylist', AgentPresentation>

export const agentList = [agents.food, agents.stylist] as const
