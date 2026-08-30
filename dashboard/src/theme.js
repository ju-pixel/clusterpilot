// Design tokens for the dashboard. Kept in step with the TUI's phosphor
// amber palette; see CLAUDE.md "TUI aesthetic".
export const T = {
  bg:       "#0a0a0a",
  panel:    "#0d0d0d",
  panel2:   "#111111",
  panel3:   "#161616",
  border:   "#1a1a1a",
  border2:  "#222222",
  border3:  "#2a2a2a",
  amber:    "#FFB866",
  amberDim: "#7a4a18",
  amberLo:  "#1e1000",
  green:    "#4ade80",
  greenDim: "#0f3a1f",
  red:      "#f87171",
  redDim:   "#3a0f0f",
  cyan:     "#67e8f9",
  cyanDim:  "#0f3a40",
  muted:    "#8899b2",
  dim:      "#5a6880",
  vdim:     "#2a2a2a",
  text:     "#fafafa",
  mono:     "'DM Mono', 'JetBrains Mono', monospace",
  sans:     "'DM Sans', system-ui, sans-serif",
};

export const STATUS = {
  RUNNING:   { fg: T.green, bg: T.greenDim, icon: "▶" },
  PENDING:   { fg: T.amber, bg: T.amberLo,  icon: "◈" },
  COMPLETED: { fg: T.cyan,  bg: T.cyanDim,  icon: "✓" },
  FAILED:    { fg: T.red,   bg: T.redDim,   icon: "✗" },
  CANCELLED: { fg: T.red,   bg: T.redDim,   icon: "✗" },
  TIMEOUT:   { fg: T.red,   bg: T.redDim,   icon: "⏰" },
};

// ── Cluster metadata (static display info — connections managed by TUI) ───────
export const CLUSTER_META = {
  cedar:  { full: "cedar.computecanada.ca",  type: "drac" },
  narval: { full: "narval.computecanada.ca", type: "drac" },
  grex:   { full: "yak.hpc.umanitoba.ca",    type: "grex" },
};

// shared button style
export const btnStyle = {
  background: T.panel2, border: `1px solid ${T.border2}`,
  borderRadius: 5, padding: "8px 14px", cursor: "pointer",
  fontFamily: T.sans, fontSize: 15, fontWeight: 500, color: T.muted,
  whiteSpace: "nowrap",
};

// ── Main Dashboard ────────────────────────────────────────────────────────────
