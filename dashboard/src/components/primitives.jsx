import { T, STATUS } from "../theme.js";

export function Glow({ color = T.amberText, children, style = {} }) {
  return (
    <span style={{ color, textShadow: `0 0 8px ${color}88`, ...style }}>
      {children}
    </span>
  );
}

export function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.PENDING;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontFamily: T.mono, fontSize: 14, fontWeight: 600,
      color: s.fg, background: s.bg,
      border: `1px solid ${s.fg}33`,
      borderRadius: 4, padding: "2px 8px",
    }}>{s.icon} {status}</span>
  );
}

export function ProgressBar({ pct, color = T.green }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 80, height: 4, background: T.vdim, borderRadius: 2, overflow: "hidden", flexShrink: 0 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>{pct}%</span>
    </div>
  );
}

export function Dot({ color }) {
  return <span style={{ color, fontSize: 11, lineHeight: 1 }}>●</span>;
}

export function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: T.sans, fontSize: 13, fontWeight: 600,
      color: T.dim, textTransform: "uppercase", letterSpacing: "0.1em",
      padding: "0 16px", marginBottom: 6,
    }}>{children}</div>
  );
}

// ── SLURM script with basic syntax colouring ──────────────────────────────────
export function SlurmScript({ src }) {
  if (!src) return (
    <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim, padding: 16 }}>
      No script stored for this job.
    </div>
  );
  return (
    <pre style={{
      margin: 0, padding: "14px 16px",
      fontFamily: T.mono, fontSize: 15, lineHeight: 1.6,
      overflowX: "auto",
    }}>
      {src.split("\n").map((line, i) => {
        let color = T.text;
        if (line.startsWith("#SBATCH")) color = T.amberText;
        else if (line.startsWith("#!")) color = T.muted;
        else if (line.startsWith("#")) color = T.dim;
        else if (/^(module|cd|julia|python|export)\b/.test(line.trim())) color = T.green;
        return <div key={i} style={{ color }}>{line || " "}</div>;
      })}
    </pre>
  );
}

// ── Pages ─────────────────────────────────────────────────────────────────────
