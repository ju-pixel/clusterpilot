// ─── shared design tokens ──────────────────────────────────────────────────────
// Single source of truth for colours, type scale, and shared component styles
// across the marketing site (LandingPage, Support, BlogPage, legal pages). Edit
// here; every page picks up the change instead of the four copies drifting apart
// (there were four `T` objects before this file existed: LandingPage, Support,
// BlogPage, and legal/LegalPage, and they had already drifted).
//
// Dark theme, warm. This is the inverse of the Fieldnotes fix, not a copy of it:
// CP stays dark and on-brand, but the pure black goes. `#fafafa` on `#000` is
// ~20:1, the harsh pairing FN's own rules ban, and the greys that softened it
// (`#6b6b6b` body copy at 3.9:1, `#444` at 2.2:1) failed WCAG AA outright. Warm
// charcoals plus warm high-contrast neutrals fix both ends: nothing here is
// below 5:1, and no pairing is harsher than 16:1. The TUI mock on the landing
// page stays the natural dark "island" it always was.
//
// Amber is the one awkward case, exactly as on the FN site but mirrored. The
// brand amber `#e8a020` is a FILL colour: button backgrounds, rules, decorative
// accents, and `ink` sits on it at 8.5:1. As TEXT on the dark grounds it is
// legible (8.5:1) but reads muddy at small sizes, so amber text (links, inline
// code, eyebrows) uses `amberText` instead. The old `#FFB866` is gone; it was
// off-brand, matching neither `#e8a020` nor the featured-image cards.
//
// These are the Section B.1 restyle tokens, and `scripts/generate-featured-image.mjs`
// already renders the blog cards from the same values. Change a ground or an ink
// here and the cards no longer match the site: change both together.
//
// Font-size floor: body text never below 16px, captions/labels/fine print never
// below 14px. F.micro (15) is the smallest size used anywhere on the site. Do
// not do arithmetic on these values at call sites (`F.micro - 1` is how a floor
// quietly stops being a floor).

export const T = {
  bg:        '#14110B',   // warm charcoal ground (replaces #000)
  panel:     '#1D1913',   // cards on the ground
  panel2:    '#26211A',   // raised / secondary panel
  border:    '#3A332A',   // hairline border
  border2:   '#4A4235',   // stronger border, featured cards
  amber:     '#e8a020',   // BRAND amber: fills, buttons, rules, accents (not text)
  amberText: '#FFC46B',   // amber as TEXT on the dark grounds (~12:1)
  ink:       '#14110B',   // near-black warm: text ON amber fills (8.5:1)
  text:      '#F2EBDD',   // primary text (~16:1, warm, never #fafafa on black)
  muted:     '#C9BEA9',   // body and secondary text (~10:1, replaces the failing #6b6b6b)
  dim:       '#9A8F7C',   // fine print (~5.9:1, replaces the failing #444)
  vdim:      '#2A241C',   // hairline divider, barely-there fills
  codeBg:    '#26211A',   // inline code chip background
  codeInk:   '#FFC46B',   // inline code text
  // ── status colours: these mirror the TUI palette (CLAUDE.md, "TUI aesthetic")
  green:     '#7BD88F',   // RUNNING
  cyan:      '#6FD8E8',   // COMPLETED
  red:       '#F08070',   // FAILED
  pending:   '#e8a020',   // PENDING (brand amber)
}

export const mono  = "'DM Mono', 'Courier New', monospace"
export const sans  = "'DM Sans', system-ui, sans-serif"
// CP-only flourish (B.4, kept deliberately): the italic serif that the blog
// featured-image cards are set in. FN has no equivalent.
export const serif = "'Playfair Display', Georgia, serif"

// ─── type scale ── edit these numbers to adjust font sizes globally ───────────
// Adopted from the Fieldnotes scale verbatim. The old site ran eyebrows at 12,
// body at 15 and buttons at 13-14, which is the "too small" half of the
// complaint; `body { font-weight: 500 }` in index.css is the other half.
export const F = {
  hero:   22,   // hero body paragraphs: the visual anchor
  body:   20,   // section description text
  card:   18,   // primary card text: step titles, headings within cards
  item:   17,   // secondary card text: feature lists, descriptions
  label:  16,   // mono labels, nav links, step numbers
  micro:  15,   // small caption/eyebrow (floor is 14; this sits above it)
  code:   17,   // inline <code> spans
  btn:    17,   // button text
  note:   16,   // small mono/italic line below hero buttons
  legal:  14,   // fine print. The floor. Nothing goes below this.
}

// ─── shared component styles ──────────────────────────────────────────────────
export const S = {
  btnAmber:  { background:T.amber, color:T.ink, fontSize:F.btn, fontWeight:700, padding:'12px 24px', borderRadius:10, border:'none', cursor:'pointer', fontFamily:mono, letterSpacing:'0.3px', whiteSpace:'nowrap' },
  btnOutline:{ background:'transparent', color:T.text, fontSize:F.btn, fontWeight:700, padding:'12px 24px', borderRadius:10, border:`1px solid ${T.border2}`, cursor:'pointer', fontFamily:mono, letterSpacing:'0.3px', whiteSpace:'nowrap' },
  label:     { display:'flex', alignItems:'center', gap:8, marginBottom:10 },
  labelDot:  { width:5, height:5, borderRadius:'50%', background:T.amber, flexShrink:0 },
  labelText: { fontFamily:mono, fontSize:F.micro, color:T.muted, letterSpacing:'1.5px', textTransform:'uppercase' },
  code:      { background:T.codeBg, padding:'2px 7px', borderRadius:4, fontFamily:mono, fontSize:F.code, color:T.codeInk },
  hr:        { border:'none', borderTop:`1px solid ${T.vdim}`, margin:0 },
}
