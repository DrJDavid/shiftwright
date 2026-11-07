import { useEffect, useRef, useState, type ReactNode } from 'react'

type Props = {
  /** Counting down toward submitting this card as-is. */
  active: boolean
  delayMs: number
  /** The user touched the card, or it can't be submitted as-is: autopilot leaves it to them. */
  onHandBack: (reason: 'user' | 'needs_input') => void
  /** Autopilot stopped here earlier because the card needs input. */
  needsInput: boolean
  children: ReactNode
}

/**
 * Wraps a routine card under autopilot: highlights it with a "Looks right, continuing…" countdown, then clicks
 * the card's own submit button, so the card's validation and result shape apply unchanged. Any click or key
 * press inside the card cancels the countdown.
 */
export function AutopilotFrame({ active, delayMs, onHandBack, needsInput, children }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const auto = useRef(false)
  const [left, setLeft] = useState(delayMs)

  useEffect(() => {
    if (!active) return
    const start = Date.now()
    setLeft(delayMs)
    const tick = setInterval(() => setLeft(Math.max(0, delayMs - (Date.now() - start))), 250)
    const fire = setTimeout(() => {
      const btn = ref.current?.querySelector<HTMLButtonElement>('button[type="submit"]')
      if (!btn || btn.disabled) {
        onHandBack('needs_input')
        return
      }
      auto.current = true
      btn.click()
      auto.current = false
    }, delayMs)
    return () => {
      clearInterval(tick)
      clearTimeout(fire)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- restart only when the countdown (re)starts
  }, [active, delayMs])

  const interrupt = () => {
    if (active && !auto.current) onHandBack('user')
  }

  return (
    <div
      ref={ref}
      onPointerDownCapture={interrupt}
      onClickCapture={interrupt}
      onKeyDownCapture={interrupt}
      className={active ? 'rounded-lg ring-2 ring-pine ring-offset-2 ring-offset-paper' : undefined}
    >
      {active && (
        <p role="status" className="mb-1 text-xs font-semibold text-pine-dark">
          Looks right, continuing… {Math.ceil(left / 1000)}
          <span className="font-normal text-muted"> · click the card to take over</span>
        </p>
      )}
      {needsInput && <p className="mb-1 text-xs font-semibold text-warn">Autopilot stopped here: this card needs your input.</p>}
      {children}
    </div>
  )
}
