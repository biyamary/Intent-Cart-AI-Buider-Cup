import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { Menu, Plus, X } from 'lucide-react'

export function SessionRail({
  title,
  newLabel,
  onNew,
  disabled,
  children,
  footer,
}: {
  title: string
  newLabel: string
  onNew: () => void
  disabled?: boolean
  children: ReactNode
  footer?: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  const openButton = useRef<HTMLButtonElement>(null)
  const rail = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!open) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    rail.current?.querySelector<HTMLElement>('button, a, [tabindex]:not([tabindex="-1"])')?.focus()
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [open])

  const close = () => {
    setOpen(false)
    requestAnimationFrame(() => openButton.current?.focus())
  }

  const containFocus = (event: KeyboardEvent<HTMLElement>) => {
    if (!open) return
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key !== 'Tab') return
    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) => element.offsetParent !== null)
    const first = focusable[0]
    const last = focusable.at(-1)
    if (!first || !last) return
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <>
      <div className="session-mobile-bar">
        <button
          ref={openButton}
          type="button"
          className="secondary"
          aria-expanded={open}
          aria-controls={id}
          onClick={() => setOpen(true)}
        >
          <Menu size={16} /> Sessions
        </button>
        <button type="button" disabled={disabled} onClick={onNew}>
          <Plus size={16} /> {newLabel}
        </button>
      </div>
      {open && (
        <button
          type="button"
          className="session-drawer-scrim"
          aria-label="Close sessions"
          onClick={close}
        />
      )}
      <aside
        ref={rail}
        id={id}
        className={`agent-session-rail ${open ? 'is-open' : ''}`}
        aria-label={title}
        aria-modal={open || undefined}
        role={open ? 'dialog' : undefined}
        onKeyDown={containFocus}
      >
        <div className="session-rail-heading">
          <div>
            <span className="eyebrow">YOUR SESSIONS</span>
            <h2>{title}</h2>
          </div>
          <button
            type="button"
            className="session-close"
            aria-label="Close sessions"
            onClick={close}
          >
            <X size={18} />
          </button>
        </div>
        <button
          type="button"
          className="session-new-button"
          disabled={disabled}
          onClick={() => {
            onNew()
            setOpen(false)
          }}
        >
          <Plus size={16} /> {newLabel}
        </button>
        <div
          className="session-rail-scroll"
          onClickCapture={(event) => {
            if ((event.target as HTMLElement).closest('[data-close-session-rail]')) setOpen(false)
          }}
        >
          {children}
        </div>
        {footer && <div className="session-rail-footer">{footer}</div>}
      </aside>
    </>
  )
}
