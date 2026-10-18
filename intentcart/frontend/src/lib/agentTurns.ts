import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { api, post } from './api'

export type TurnStage =
  | 'queued'
  | 'understanding'
  | 'planning'
  | 'searching'
  | 'researching'
  | 'preparing'
  | 'complete'
  | 'failed'

export interface RetryAdvice {
  allowed: boolean
  after_seconds: number | null
  use_new_request_id: true
}

export interface TurnStatus {
  request_id: string
  agent_id: string
  session_id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed'
  progress: { stage: TurnStage; label: string }
  created_at: number
  updated_at: number
  error: { code: string; message: string } | null
  retry: RetryAdvice | null
}

export interface TurnRequest {
  text: string
  request_id: string
  attachments?: string[]
}

type ActiveTurn<TBody> = {
  sessionId: string
  body: TBody
  initial: TurnStatus
  startedAt: number
}

/**
 * Accept a conversational turn quickly, then poll its safe server-owned progress.
 * The pending request remains visible until the canonical transcript has reloaded.
 */
export function useAgentTurn<TBody extends TurnRequest>({
  agentId,
  ensureSession,
  onAccepted,
  onFinished,
}: {
  agentId: string
  ensureSession: () => Promise<string>
  onAccepted?: (body: TBody, sessionId: string) => void
  onFinished: (status: TurnStatus, sessionId: string) => Promise<void> | void
}) {
  const [active, setActive] = useState<ActiveTurn<TBody> | null>(null)
  const finishing = useRef<string | null>(null)
  const acceptedCallback = useRef(onAccepted)
  const finishedCallback = useRef(onFinished)

  useEffect(() => {
    acceptedCallback.current = onAccepted
    finishedCallback.current = onFinished
  }, [onAccepted, onFinished])

  const accept = useMutation({
    retry: false,
    mutationFn: async (body: TBody) => {
      const sessionId = await ensureSession()
      const status = await post<TurnStatus>(`/agents/${agentId}/sessions/${sessionId}/turns`, body)
      return { body, sessionId, status }
    },
    onSuccess: ({ body, sessionId, status }) => {
      setActive({ sessionId, body, initial: status, startedAt: status.created_at * 1000 })
      acceptedCallback.current?.(body, sessionId)
    },
  })

  const turn = useQuery({
    queryKey: ['agent-turn', agentId, active?.sessionId, active?.body.request_id],
    queryFn: () =>
      api<TurnStatus>(
        `/agents/${agentId}/sessions/${active!.sessionId}/turns/${active!.body.request_id}`,
      ),
    enabled: Boolean(active),
    placeholderData: active?.initial,
    retry: 3,
    retryDelay: (attempt) => Math.min(500 * 2 ** attempt, 3000),
    refetchInterval: (query) => {
      const status = query.state.data?.status
      return status === 'succeeded' || status === 'failed' ? false : 900
    },
  })
  const status = turn.data ?? active?.initial ?? null

  useEffect(() => {
    if (!active || !status || !['succeeded', 'failed'].includes(status.status)) return
    if (finishing.current === status.request_id) return
    finishing.current = status.request_id
    Promise.resolve(finishedCallback.current(status, active.sessionId)).finally(() => {
      setActive((current) => (current?.body.request_id === status.request_id ? null : current))
      finishing.current = null
      accept.reset()
    })
  }, [active, status, accept])

  return {
    send: accept,
    activeRequest: active?.body ?? null,
    sessionId: active?.sessionId ?? null,
    status,
    startedAt: active?.startedAt,
    pollError: turn.error,
    retryProgress: turn.refetch,
    isRunning: accept.isPending || Boolean(active),
  }
}
