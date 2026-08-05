import './CrestLogo.css'

/**
 * The CleanMuzik crest — Rev C, owner-approved at the T-105 design gate
 * (docs/r1/design/crest-logo.html). A wide badge with a 3D crown and CLEAN/MUZIK
 * stacked in block-letter paths (10×14 glyph grid), OutKast-style.
 *
 * Pure SVG, no <text> and no font: the letters are drawn paths, so the mark renders
 * identically everywhere. Everything is `currentColor` — depth comes from 0.35
 * fill-opacity fills, not a second colour — so `color` on the wrapper themes it
 * (cyan #3fb6d8 dark / #0e7d9c light, both carried by --accent).
 */
export function CrestLogo() {
  return (
    <span className="crest">
      {/* Glyph definitions + the crest symbol. Hidden; referenced by <use> below. */}
      <svg width="0" height="0" className="crest__defs" aria-hidden="true" focusable="false">
        <defs>
          {/* Block glyphs — fat bars on a 10 × 14 box */}
          <path id="sC" d="M0,0 H10 V4 H3.8 V10 H10 V14 H0 Z" />
          <path id="sL" d="M0,0 H3.8 V10.2 H10 V14 H0 Z" />
          <path id="sE" d="M0,0 H10 V3.4 H3.8 V5.7 H9.4 V8.3 H3.8 V10.6 H10 V14 H0 Z" />
          <path id="sA" fillRule="evenodd" d="M0,14 V0 H10 V14 H6.4 V10.8 H3.6 V14 Z M3.6,3.6 H6.4 V7.2 H3.6 Z" />
          <path id="sN" d="M0,14 V0 H3.5 L6.5,7.8 V0 H10 V14 H6.5 L3.5,6.2 V14 Z" />
          <path id="sM" d="M0,14 V0 H3.4 L5,4.6 L6.6,0 H10 V14 H6.8 V6.8 L5,10.8 L3.2,6.8 V14 Z" />
          <path id="sU" d="M0,0 H3.8 V10.2 H6.2 V0 H10 V14 H0 Z" />
          <path id="sZ" d="M0,0 H10 V3.8 L5.2,10.2 H10 V14 H0 V10.2 L4.8,3.8 H0 Z" />
          <path id="sI" d="M0,0 H10 V3.6 H6.9 V10.4 H10 V14 H0 V10.4 H3.1 V3.6 H0 Z" />
          <path id="sK" d="M0,0 H3.6 V4.8 L6.9,0 H10 L5.9,7 L10,14 H6.7 L3.6,8.9 V14 H0 Z" />

          {/* Rev C: wide badge, wing-tip corners, curly-brace bottom, 3D crown.
              A plain <g>, NOT a <symbol>: a <use>→<symbol> creates a nested viewport
              pinned at the use's (0,0), so a symbol whose own viewBox has a non-zero
              origin ("22 -8 …") shifts the artwork left of the visible window and the
              left wing clips — widening the box can't fix an offset. As a <g> there is
              no nested viewport; the outer `.crest__mark` svg's viewBox is the only
              transform, and its ~8-unit padding (badge strokes reach x≈30/230 at
              strokeWidth 4) clears every edge. */}
          <g id="crest-c">
            {/* badge outline: outer, split at the top where the crown band overlaps */}
            <g fill="none" stroke="currentColor" strokeWidth="4" strokeLinejoin="round" strokeLinecap="round">
              <path d="M84,50 H32 L56,58 L58,98 L66,128 C72,134 82,137 98,136.5 C110,136 118,135 123,134 Q127,137 130,138" />
              <path d="M176,50 H228 L204,58 L202,98 L194,128 C188,134 178,137 162,136.5 C150,136 142,135 137,134 Q133,137 130,138" />
            </g>
            {/* inner echo line: uniform 6-unit offset of the outer, split under the band */}
            <g fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinejoin="round" strokeLinecap="round">
              <path d="M88,56 H62 L64,97.7 L71.8,126.4 C77,129.5 86,131.3 99,130.6 C109.5,130.1 117,129.1 122,128.1 Q126.6,131.1 130,132.1" />
              <path d="M172,56 H198 L196,97.7 L188.2,126.4 C183,129.5 174,131.3 161,130.6 C150.5,130.1 143,129.1 138,128.1 Q133.4,131.1 130,132.1" />
            </g>
            {/* crown band: darker translucent fill = 3D depth, bowed in perspective */}
            <path
              d="M86,40 Q130,46 174,40 L174,52 Q130,60 86,52 Z"
              fill="currentColor"
              fillOpacity="0.35"
              stroke="currentColor"
              strokeWidth="3.5"
              strokeLinejoin="round"
            />
            {/* five points rising off the bowed band top */}
            <path
              d="M86,40 L90,26 L98,41 L110,21 L118,43 L130,18 L142,43 L150,21 L158,41 L170,26 L174,40"
              fill="none"
              stroke="currentColor"
              strokeWidth="3.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            {/* orbs, with darker lower-half shading for volume */}
            <g fill="none" stroke="currentColor" strokeWidth="3">
              <circle cx="90" cy="19.5" r="4.2" />
              <circle cx="110" cy="14.5" r="4.2" />
              <circle cx="130" cy="11" r="4.6" />
              <circle cx="150" cy="14.5" r="4.2" />
              <circle cx="170" cy="19.5" r="4.2" />
            </g>
            <g fill="currentColor" fillOpacity="0.35" stroke="none">
              <path d="M86.4,20.5 A3.6,3.6 0 0 0 93.6,20.5 Z" />
              <path d="M106.4,15.5 A3.6,3.6 0 0 0 113.6,15.5 Z" />
              <path d="M126.1,12 A3.9,3.9 0 0 0 133.9,12 Z" />
              <path d="M146.4,15.5 A3.6,3.6 0 0 0 153.6,15.5 Z" />
              <path d="M166.4,20.5 A3.6,3.6 0 0 0 173.6,20.5 Z" />
            </g>
            {/* wordmark: CLEAN big, divider, MUZIK — packed against the edges */}
            <g fill="currentColor" stroke="currentColor" strokeWidth="0.8" strokeLinejoin="round">
              <g transform="translate(66.27,60) scale(2.26)">
                <use href="#sC" />
                <use href="#sL" x="11.6" />
                <use href="#sE" x="23.2" />
                <use href="#sA" x="34.8" />
                <use href="#sN" x="46.4" />
              </g>
              <g transform="translate(78.7,99) scale(1.82)">
                <use href="#sM" />
                <use href="#sU" x="11.6" />
                <use href="#sZ" x="23.2" />
                <use href="#sI" x="34.8" />
                <use href="#sK" x="46.4" />
              </g>
            </g>
            <path d="M68,95.4 H192" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
          </g>
        </defs>
      </svg>

      {/* Decorative: the wordmark beside it carries the accessible name, so the mark
          is aria-hidden to avoid announcing "CleanMuzik" twice. */}
      <svg className="crest__mark" viewBox="22 -8 216 160" aria-hidden="true" focusable="false">
        <use href="#crest-c" />
      </svg>
    </span>
  )
}
