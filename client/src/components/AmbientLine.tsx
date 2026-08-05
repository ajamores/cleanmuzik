import './AmbientLine.css'

/**
 * The ambient equalizer behind everything (owner request, replacing the drifting
 * wave — and deliberately reversing the old "no spectrum bars" note; the owner
 * asked for spectrum bars by reference).
 *
 * A row of segmented vertical bars along the bottom of the viewport, VU-meter
 * style: each bar is a fixed, fully-painted LED column (bright cyan at the base
 * fading to blue up top, with sparse magenta accents assigned in the stylesheet)
 * behind a page-coloured cover that slides up and down on `transform` only. The
 * cover reveal is what animates, so the LED segments stay pixel-crisp and the
 * whole thing composites on the GPU. Per-bar duration/phase come from a
 * deterministic hash of the bar index, so the field bounces like a beat rather
 * than sweeping, and renders identically on every load.
 *
 * Decorative only (`aria-hidden`), sits at z-index 0 behind the app content, and
 * freezes under `prefers-reduced-motion` into a static skyline (each cover rests
 * at its own `--rest` height) — handled in the stylesheet.
 */
const BAR_COUNT = 36

interface BarRhythm {
  dur: number
  delay: number
  rest: number
}

/** Deterministic per-bar rhythm — a hash of the index, not Math.random(), so the
 *  skyline is stable across renders, reloads and the reduced-motion freeze. */
const RHYTHM: BarRhythm[] = Array.from({ length: BAR_COUNT }, (_, i) => {
  const h = Math.imul(i + 1, 2654435761) >>> 0
  return {
    dur: 1.7 + ((h >>> 8) % 140) / 100, // 1.7s – 3.1s
    delay: -(((h >>> 16) % 300) / 100), // negative: every bar starts mid-cycle
    rest: 26 + ((h >>> 4) % 52), // 26% – 78% lit when frozen
  }
})

export function AmbientLine() {
  return (
    <div className="ambient" aria-hidden="true">
      {RHYTHM.map((bar, i) => (
        <span className="ambient__bar" key={i}>
          <span className="ambient__leds" />
          <span
            className="ambient__cover"
            style={{
              animationDuration: `${bar.dur}s`,
              animationDelay: `${bar.delay}s`,
              ['--rest' as string]: `-${bar.rest}%`,
            }}
          />
        </span>
      ))}
    </div>
  )
}
