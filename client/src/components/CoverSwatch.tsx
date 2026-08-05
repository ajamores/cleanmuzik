/**
 * A deterministic gradient swatch standing in for cover art (T-105, Option 2).
 *
 * NOT the real album cover: the app embeds art into the landed MP3 but never serves
 * the bytes back, so this is a decorative token that says "this track carries art",
 * seeded off the track's identity so the same song always draws the same swatch.
 * Real cover art is a deferred follow-up; until then this fills the art slot the
 * design gate approved without pretending to be the genuine image.
 *
 * Theme-independent by design — art is art in both light and dark.
 */
export function CoverSwatch({
  seed,
  size = 46,
  className,
}: {
  seed: string
  size?: number
  className?: string
}) {
  const h = hash(seed)
  const hue = h % 360
  const hue2 = (hue + 40 + (h % 40)) % 360
  const from = `hsl(${hue}, 46%, 22%)`
  const to = `hsl(${hue2}, 58%, 52%)`
  // Unique gradient id per seed so multiple swatches on one page don't collide.
  const gid = `cover-${(h >>> 0).toString(36)}`

  return (
    <span className={className ? `cover-swatch ${className}` : 'cover-swatch'} aria-hidden="true">
      <svg viewBox="0 0 46 46" width={size} height={size}>
        <defs>
          <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor={from} />
            <stop offset="1" stopColor={to} />
          </linearGradient>
        </defs>
        <rect width="46" height="46" fill={`url(#${gid})`} />
        <circle cx="23" cy="23" r="9" fill="none" stroke="#eaf6fb" strokeWidth="1.4" opacity="0.85" />
        <circle cx="23" cy="23" r="2" fill="#eaf6fb" />
      </svg>
    </span>
  )
}

/** Small stable string hash (FNV-1a-ish). Deterministic across renders and reloads. */
function hash(s: string): number {
  let h = 2166136261
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 16777619)
  }
  return Math.abs(h)
}
