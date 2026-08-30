// Design tokens for the dashboard.
//
// These are the B.1 brand tokens from frontend/src/theme.js, which the
// marketing site, the blog cards and the featured-image generator already
// share. The dashboard was the last surface still on the palette that file
// retired, and it retired it for reasons that applied here too: #fafafa on
// #0a0a0a is 19:1, which is uncomfortable to read for any length of time,
// and #FFB866 matched neither the brand amber nor the cards.
//
// The one rule worth knowing before editing: `amber` is a FILL colour, for
// button backgrounds, borders, rules and tints. As text it reads muddy at
// small sizes, so amber TEXT uses `amberText`. Text sitting ON an amber fill
// uses `ink`. Getting this backwards is the easiest mistake to make here.
//
// The `*Dim` status grounds and `panel3` / `border3` have no equivalent in
// the brand file; they are derived here and warmed to match the ground.
// Every status pill clears AA against its own ground: green 7.8:1, cyan
// 8.2:1, red 5.7:1, amber 10.1:1.
export const T = {
  bg:       "#14110B",   // warm charcoal ground
  panel:    "#1D1913",   // cards and bars on the ground
  panel2:   "#26211A",   // raised / secondary panel, inputs
  panel3:   "#2F2921",   // raised again
  border:   "#3A332A",   // hairline
  border2:  "#4A4235",   // stronger border
  border3:  "#5A5142",   // strongest
  amber:    "#e8a020",   // BRAND amber: fills, buttons, rules, tints. Not text.
  amberText:"#FFC46B",   // amber as TEXT on the dark grounds (~12:1)
  ink:      "#14110B",   // text ON an amber fill (8.5:1)
  amberDim: "#7A6134",   // decorative dim amber
  amberLo:  "#2A2118",   // very dark amber fill, callout grounds
  green:    "#7BD88F",   // RUNNING
  greenDim: "#1B3323",
  red:      "#F08070",   // FAILED
  redDim:   "#3A211C",
  cyan:     "#6FD8E8",   // COMPLETED
  cyanDim:  "#16332F",
  muted:    "#C9BEA9",   // body and secondary text (~10:1)
  dim:      "#9A8F7C",   // fine print (~5.9:1)
  vdim:     "#2A241C",   // hairline divider, barely-there fill
  text:     "#F2EBDD",   // primary text (15.9:1, warm, never #fafafa)
  mono:     "'DM Mono', 'JetBrains Mono', monospace",
  sans:     "'DM Sans', system-ui, sans-serif",
};

export const STATUS = {
  RUNNING:   { fg: T.green, bg: T.greenDim, icon: "▶" },
  PENDING:   { fg: T.amberText, bg: T.amberLo, icon: "◈" },
  COMPLETED: { fg: T.cyan,  bg: T.cyanDim,  icon: "✓" },
  FAILED:    { fg: T.red,   bg: T.redDim,   icon: "✗" },
  CANCELLED: { fg: T.red,   bg: T.redDim,   icon: "✗" },
  TIMEOUT:   { fg: T.red,   bg: T.redDim,   icon: "⏰" },
};

// ── Cluster metadata (static display info — connections managed by TUI) ───────
export const CLUSTER_META = {
  cedar:  { full: "cedar.computecanada.ca",  type: "drac" },
  narval: { full: "narval.computecanada.ca", type: "drac" },
  grex:   { full: "grex.hpc.umanitoba.ca",   type: "grex" },
};

// shared button style
export const btnStyle = {
  background: T.panel2, border: `1px solid ${T.border2}`,
  borderRadius: 5, padding: "8px 14px", cursor: "pointer",
  fontFamily: T.sans, fontSize: 15, fontWeight: 500, color: T.muted,
  whiteSpace: "nowrap",
};
