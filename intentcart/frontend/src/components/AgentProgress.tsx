import { useEffect, useState } from 'react'
import { Check, LoaderCircle } from 'lucide-react'

export type AgentProgressStage = {
  id: string
  label: string
}

export function AgentProgress({
  agentName,
  stage,
  label,
  stages = [],
  startedAt,
}: {
  agentName: string
  stage?: string | null
  label?: string | null
  stages?: AgentProgressStage[]
  startedAt?: number
}) {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = startedAt ?? Date.now()
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - started) / 1000)))
    update()
    const timer = window.setInterval(update, 1000)
    return () => window.clearInterval(timer)
  }, [startedAt])

  const currentIndex = stage ? stages.findIndex((item) => item.id === stage) : -1
  const message = label
    ? label
    : currentIndex >= 0
      ? stages[currentIndex].label
      : elapsed >= 15
        ? 'Still working — detailed checks can take a minute.'
        : 'Working on your request…'

  return (
    <div className="agent-progress" role="status" aria-live="polite">
      <div className="progress-heading">
        <span className="progress-spinner" aria-hidden="true">
          <LoaderCircle size={16} />
        </span>
        <div>
          <strong>{agentName}</strong>
          <span>{message}</span>
        </div>
        <time>{elapsed}s</time>
      </div>
      {stages.length > 0 && currentIndex >= 0 && (
        <ol className="progress-steps" aria-label="Request progress">
          {stages.map((item, index) => (
            <li
              key={item.id}
              className={
                index < currentIndex ? 'is-complete' : index === currentIndex ? 'is-current' : ''
              }
            >
              <span aria-hidden="true">{index < currentIndex ? <Check size={10} /> : null}</span>
              {item.label}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
