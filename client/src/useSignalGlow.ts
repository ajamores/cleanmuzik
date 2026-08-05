import { useEffect } from 'react'

/**
 * The signal follows the pointer (T-105, ADR-018). One document-level listener feeds
 * the cursor's position (as --mx/--my, local to the element) into whichever
 * `.signal-glow` element is under it, so its `::after` radial glow pools under the
 * hand. One listener rather than per-card handlers: cards mount and unmount as jobs
 * come and go, and a single delegated listener never leaks.
 *
 * Inert under `prefers-reduced-motion` — the media query is read live on every move
 * (not captured once), so a mid-session preference change is honoured, and the CSS
 * hides the glow layer there regardless.
 */
export function useSignalGlow() {
  useEffect(() => {
    // `matchMedia` is absent under jsdom/SSR; optional-chain it and treat a missing
    // query as "motion allowed" so the glow still works where the API exists.
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    function onMove(e: PointerEvent) {
      if (reduce?.matches) return
      const target = e.target as Element | null
      const el = target?.closest?.('.signal-glow') as HTMLElement | null
      if (!el) return
      const r = el.getBoundingClientRect()
      el.style.setProperty('--mx', `${e.clientX - r.left}px`)
      el.style.setProperty('--my', `${e.clientY - r.top}px`)
    }
    document.addEventListener('pointermove', onMove, { passive: true })
    return () => document.removeEventListener('pointermove', onMove)
  }, [])
}
