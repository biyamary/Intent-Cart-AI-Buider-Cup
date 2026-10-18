export interface AgentInfo {
  id: string
  name: string
  enabled: boolean
  capabilities: string[]
}
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  text: string
  created_at: number
  status: 'complete' | 'error'
  sources: { title: string; url: string }[]
  citations: { text: string; source_indices: number[] }[]
  search_queries: string[]
  search_entry_point: string | null
  attachments?: string[]
}
export interface ConversationSummary {
  id: string
  agent_id: string
  title: string
  updated_at: number
}
export interface Conversation extends ConversationSummary {
  messages: ChatMessage[]
  look_id?: string | null
}
export function safeWebUrl(value: string | undefined) {
  try {
    const url = new URL(value ?? '')
    return ['https:', 'http:'].includes(url.protocol) && !url.username ? url.href : undefined
  } catch {
    return undefined
  }
}
