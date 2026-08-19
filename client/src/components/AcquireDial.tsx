import { useCallback, useRef } from 'react'
import './AcquireDial.css'

/**
 * The three resting stops of the acquire dial (ADR-029, T-310 design gate D1–D4).
 *
 * `single` and `playlist` are the wired intents the dial submits; `multi` is a
 * present-but-inert stop ("soon") — it reserves the control's geometry and puts the
 * roadmap on screen, but its build is backlog (T-046) and the backend refuses it, so it
 * is selectable-for-preview yet never actually acquires. App derives the submit intent
 * from the mode and only ever sends `single`/`playlist`.
 */
export type DialMode = 'single' | 'playlist' | 'multi'

const STOPS: { mode: DialMode; label: string; soon?: boolean }[] = [
  { mode: 'single', label: 'Single' },
  { mode: 'playlist', label: 'Playlist' },
  { mode: 'multi', label: 'Multi', soon: true },
]

interface AcquireDialProps {
  mode: DialMode
  onChange: (mode: DialMode) => void
}

/**
 * The acquire-intent control — a round detented selector, the one round object in a
 * sharp-cornered instrument (deliberately a hero control; ADR-029).
 *
 * It is an **accessible radiogroup, not a knob you drag**: the pointer rotates to the
 * chosen stop purely as decoration over three `role="radio"` labels. Roving tabindex +
 * arrow keys move between stops the way ARIA prescribes, so it works from the keyboard
 * with no pointer at all. Single is the resting default every load, so the R1 walk-away
 * flow is untouched — the dial adds no step to the common case.
 *
 * The real fix underneath the ornament: the app stops guessing intent from URL shape.
 * The mode *is* the answer to the ambiguous `watch?v=X&list=PL…` paste, so there is no
 * "which did you mean?" prompt — the owner said it up front.
 */
export function AcquireDial({ mode, onChange }: AcquireDialProps) {
  const groupRef = useRef<HTMLDivElement>(null)

  // Arrow keys walk the stops and select as they land (ARIA radiogroup semantics —
  // moving focus in a radiogroup checks the option, it isn't a separate commit). Wraps at
  // the ends; Home/End jump to the first/last. Focus follows selection so the roving
  // tabindex stays on the checked stop.
  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      const i = STOPS.findIndex((s) => s.mode === mode)
      let next: number
      switch (e.key) {
        case 'ArrowRight':
        case 'ArrowDown':
          next = (i + 1) % STOPS.length
          break
        case 'ArrowLeft':
        case 'ArrowUp':
          next = (i - 1 + STOPS.length) % STOPS.length
          break
        case 'Home':
          next = 0
          break
        case 'End':
          next = STOPS.length - 1
          break
        default:
          return
      }
      e.preventDefault()
      onChange(STOPS[next].mode)
      // Move focus to the newly-checked stop so the next arrow keys start from here.
      const radios = groupRef.current?.querySelectorAll<HTMLElement>('[role="radio"]')
      radios?.[next]?.focus()
    },
    [mode, onChange],
  )

  return (
    <div className="dial-wrap">
      <div
        ref={groupRef}
        className="dial"
        data-mode={mode}
        role="radiogroup"
        aria-label="Acquire mode"
        onKeyDown={onKeyDown}
      >
        {/* The knob is pure ornament — the pointer's angle is driven by `data-mode` in
            CSS. It carries no role: the radios below are the actual controls. */}
        <div className="dial__knob" aria-hidden="true">
          <span className="dial__pointer" />
          <span className="dial__cap" />
        </div>
        {STOPS.map((stop) => {
          const on = stop.mode === mode
          return (
            <span
              key={stop.mode}
              className={`dial__lab dial__lab--${stop.mode}`}
              role="radio"
              aria-checked={on}
              aria-label={stop.soon ? `${stop.label} (coming soon)` : stop.label}
              data-on={on}
              tabIndex={on ? 0 : -1}
              onClick={() => onChange(stop.mode)}
            >
              {stop.label}
              {stop.soon && <i>·soon</i>}
            </span>
          )
        })}
      </div>
    </div>
  )
}
