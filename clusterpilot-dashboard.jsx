import { useState } from "react";

// ── Design tokens (matches shared system in product-development-plan-v2) ───────
const T = {
  bg:       "#0a0a0a",
  panel:    "#0d0d0d",
  panel2:   "#111111",
  panel3:   "#161616",   // card/row surface
  border:   "#1a1a1a",
  border2:  "#222222",
  border3:  "#2a2a2a",
  amber:    "#FFB866",   // CP primary accent
  amberDim: "#7a4a18",
  amberLo:  "#1e1000",
  green:    "#4ade80",   // running / active states
  greenDim: "#0f3a1f",
  red:      "#f87171",
  redDim:   "#3a0f0f",
  cyan:     "#67e8f9",   // completed states
  cyanDim:  "#0f3a40",
  muted:    "#8899b2",   // steel blue-grey
  dim:      "#5a6880",
  vdim:     "#2a2a2a",
  text:     "#fafafa",
  mono:     "'DM Mono', 'JetBrains Mono', monospace",
  sans:     "'DM Sans', system-ui, sans-serif",
};

const STATUS = {
  RUNNING:   { fg: T.green, bg: T.greenDim, icon: "▶" },
  PENDING:   { fg: T.amber, bg: T.amberLo,  icon: "◈" },
  COMPLETED: { fg: T.cyan,  bg: T.cyanDim,  icon: "✓" },
  FAILED:    { fg: T.red,   bg: T.redDim,   icon: "✗" },
};

// ── Sample data ───────────────────────────────────────────────────────────────
const JOBS = [
  { id: "15042891", name: "mc_sweep_T100_400",  status: "RUNNING",   cluster: "cedar",  partition: "gpu",    gpus: "A100×2", elapsed: "3:42:17", walltime: "8:00:00",  pct: 46,  submitted: "2026-03-29 09:14", account: "def-mlafond", node: "cdr2345",  mem: "31.2/32G" },
  { id: "15042654", name: "dipole_N1024_equil", status: "PENDING",   cluster: "narval", partition: "gpu",    gpus: "A100×4", elapsed: null,      walltime: "12:00:00", pct: 0,   submitted: "2026-03-29 09:08", account: "def-mlafond", node: null,        mem: null },
  { id: "15041998", name: "spinwave_k_scan",    status: "RUNNING",   cluster: "grex",   partition: "stamps", gpus: "V100×4", elapsed: "1:05:44", walltime: "4:00:00",  pct: 27,  submitted: "2026-03-29 08:53", account: "def-stamps",  node: "tatanka2",  mem: "14.8/16G" },
  { id: "15040777", name: "mc_equil_run_09",    status: "COMPLETED", cluster: "cedar",  partition: "gpu",    gpus: "A100×2", elapsed: "5:11:03", walltime: "6:00:00",  pct: 100, submitted: "2026-03-29 01:22", account: "def-mlafond", node: "cdr2298",   mem: "32.0/32G" },
  { id: "15039450", name: "benchmark_N128",     status: "FAILED",    cluster: "grex",   partition: "stamps", gpus: "V100×4", elapsed: "0:03:12", walltime: "1:00:00",  pct: 5,   submitted: "2026-03-28 22:10", account: "def-stamps",  node: "tatanka3",  mem: "4.1/8G"  },
  { id: "15038201", name: "suscept_chi_scan",   status: "COMPLETED", cluster: "narval", partition: "gpu",    gpus: "A100×1", elapsed: "9:58:44", walltime: "10:00:00", pct: 100, submitted: "2026-03-28 18:45", account: "def-mlafond", node: "ng10042",   mem: "7.9/8G"  },
  { id: "15037090", name: "order_param_sweep",  status: "COMPLETED", cluster: "cedar",  partition: "gpu",    gpus: "A100×2", elapsed: "7:22:01", walltime: "8:00:00",  pct: 100, submitted: "2026-03-28 12:11", account: "def-mlafond", node: "cdr2301",   mem: "31.5/32G" },
];

const SLURM_SCRIPTS = {
  "15042891": `#!/bin/bash
#SBATCH --job-name=mc_sweep_T100_400
#SBATCH --account=def-mlafond
#SBATCH --gres=gpu:a100:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=%x-%j.out

module load julia/1.10.4 cuda/12.2

cd $SCRATCH/clusterpilot_jobs/mc_sweep_T100_400

julia --project=. run_simulation.jl \\
  --config config.toml \\
  --output $SCRATCH/results/$SLURM_JOB_ID`,
};

const LOGS = {
  "15042891": [
    "[ 0.00s] SpinGlassLab v2.1.4 initialising",
    "[ 0.12s] CUDA device: NVIDIA A100-SXM4-80GB (×2)",
    "[ 0.13s] Loading assembly: N=1024, periodic BCs",
    "[ 0.41s] Dipole interaction tensor computed",
    "[ 0.42s] Starting sweep: T ∈ [100K, 400K], 50 steps",
    "[892.3s] T=100K done  │ <M>=0.9821 │ χ=0.0031",
    "[1847s] T=108K done  │ <M>=0.9744 │ χ=0.0038",
    "[2891s] T=116K done  │ <M>=0.9601 │ χ=0.0052",
    "[3744s] T=124K done  │ <M>=0.9389 │ χ=0.0079",
    "[4601s] T=132K done  │ <M>=0.9104 │ χ=0.0118",
    "[5512s] T=140K done  │ <M>=0.8751 │ χ=0.0181",
    "[6489s] T=148K done  │ <M>=0.8244 │ χ=0.0294",
    "[7401s] T=156K ──── currently running ────",
  ],
};

const CLUSTERS = [
  { name: "cedar.computecanada.ca",  short: "cedar",  type: "drac", status: "connected", running: 2, pending: 1 },
  { name: "narval.computecanada.ca", short: "narval", type: "drac", status: "connected", running: 0, pending: 1 },
  { name: "yak.hpc.umanitoba.ca",    short: "grex",   type: "grex", status: "connected", running: 1, pending: 0 },
];

// ── Primitives ────────────────────────────────────────────────────────────────
function Glow({ color = T.amber, children, style = {} }) {
  return (
    <span style={{ color, textShadow: `0 0 8px ${color}88`, ...style }}>
      {children}
    </span>
  );
}

function StatusBadge({ status }) {
  const s = STATUS[status] || STATUS.PENDING;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontFamily: T.mono, fontSize: 11, fontWeight: 600,
      color: s.fg, background: s.bg,
      border: `1px solid ${s.fg}33`,
      borderRadius: 4, padding: "2px 8px",
    }}>{s.icon} {status}</span>
  );
}

function ProgressBar({ pct, color = T.green }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ width: 80, height: 4, background: T.vdim, borderRadius: 2, overflow: "hidden", flexShrink: 0 }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color, borderRadius: 2 }} />
      </div>
      <span style={{ fontFamily: T.mono, fontSize: 11, color: T.dim }}>{pct}%</span>
    </div>
  );
}

function Dot({ color }) {
  return <span style={{ color, fontSize: 8, lineHeight: 1 }}>●</span>;
}

function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: T.sans, fontSize: 10, fontWeight: 600,
      color: T.dim, textTransform: "uppercase", letterSpacing: "0.1em",
      padding: "0 16px", marginBottom: 6,
    }}>{children}</div>
  );
}

// ── SLURM script with basic syntax colouring ──────────────────────────────────
function SlurmScript({ src }) {
  if (!src) return (
    <div style={{ fontFamily: T.mono, fontSize: 12, color: T.dim, padding: 16 }}>
      No script stored for this job.
    </div>
  );
  return (
    <pre style={{
      margin: 0, padding: "14px 16px",
      fontFamily: T.mono, fontSize: 12, lineHeight: 1.6,
      overflowX: "auto",
    }}>
      {src.split("\n").map((line, i) => {
        let color = T.text;
        if (line.startsWith("#SBATCH")) color = T.amber;
        else if (line.startsWith("#!")) color = T.muted;
        else if (line.startsWith("#")) color = T.dim;
        else if (/^(module|cd|julia|python|export)\b/.test(line.trim())) color = T.green;
        return <div key={i} style={{ color }}>{line || " "}</div>;
      })}
    </pre>
  );
}

// ── Pages ─────────────────────────────────────────────────────────────────────

function JobsPage() {
  const [selectedId, setSelectedId] = useState("15042891");
  const [detailTab, setDetailTab] = useState("script");

  const job = JOBS.find(j => j.id === selectedId);
  const sc = job ? STATUS[job.status] : null;

  return (
    <div style={{ display: "flex", flex: 1, overflow: "hidden", gap: 0 }}>

      {/* ── JOB TABLE ──────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflow: "auto", borderRight: `1px solid ${T.border}` }}>

        {/* table header */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 100px 90px 90px 160px 90px",
          padding: "10px 20px",
          borderBottom: `1px solid ${T.border}`,
          background: T.panel,
          position: "sticky", top: 0, zIndex: 1,
        }}>
          {["Job", "Status", "Cluster", "Partition", "Walltime used / req.", "Submitted"].map(h => (
            <div key={h} style={{
              fontFamily: T.sans, fontSize: 11, fontWeight: 600,
              color: T.dim, textTransform: "uppercase", letterSpacing: "0.07em",
            }}>{h}</div>
          ))}
        </div>

        {JOBS.map(j => {
          const s = STATUS[j.status];
          const active = j.id === selectedId;
          return (
            <div key={j.id} onClick={() => setSelectedId(j.id)} style={{
              display: "grid",
              gridTemplateColumns: "1fr 100px 90px 90px 160px 90px",
              padding: "11px 20px",
              borderBottom: `1px solid ${T.border}`,
              background: active ? `${T.amber}08` : "transparent",
              borderLeft: `2px solid ${active ? T.amber : "transparent"}`,
              cursor: "pointer",
              alignItems: "center",
            }}>
              {/* name + id */}
              <div>
                <div style={{ fontFamily: T.sans, fontSize: 13, color: T.text, fontWeight: active ? 500 : 400 }}>
                  {j.name}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginTop: 2 }}>
                  #{j.id}
                </div>
              </div>
              {/* status */}
              <div><StatusBadge status={j.status} /></div>
              {/* cluster */}
              <div style={{ fontFamily: T.mono, fontSize: 12, color: T.muted }}>{j.cluster}</div>
              {/* partition */}
              <div style={{ fontFamily: T.mono, fontSize: 12, color: T.dim }}>{j.partition}</div>
              {/* walltime */}
              <div>
                <div style={{ fontFamily: T.mono, fontSize: 12, color: s.fg }}>
                  {j.elapsed ?? "─:──:──"} / {j.walltime}
                </div>
                {j.status !== "PENDING" && (
                  <div style={{ marginTop: 5 }}>
                    <ProgressBar pct={j.pct} color={s.fg} />
                  </div>
                )}
              </div>
              {/* submitted */}
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim }}>{j.submitted}</div>
            </div>
          );
        })}
      </div>

      {/* ── JOB DETAIL ──────────────────────────────────────────────────── */}
      {job && (
        <div style={{
          width: 420, flexShrink: 0,
          display: "flex", flexDirection: "column",
          overflow: "hidden",
        }}>
          {/* detail header */}
          <div style={{
            padding: "14px 18px",
            borderBottom: `1px solid ${T.border}`,
            background: T.panel,
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6 }}>
              <span style={{ fontFamily: T.sans, fontSize: 14, fontWeight: 600, color: T.text }}>
                {job.name}
              </span>
              <StatusBadge status={job.status} />
            </div>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {[
                ["cluster",   job.cluster],
                ["partition", job.partition],
                ["GPUs",      job.gpus],
                ["node",      job.node ?? "─"],
                ["mem",       job.mem  ?? "─"],
                ["account",   job.account],
              ].map(([k, v]) => (
                <div key={k}>
                  <span style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }}>{k} </span>
                  <span style={{ fontFamily: T.mono, fontSize: 11, color: T.muted }}>{v}</span>
                </div>
              ))}
            </div>
          </div>

          {/* tabs */}
          <div style={{
            display: "flex", gap: 0,
            borderBottom: `1px solid ${T.border}`,
            background: T.panel,
          }}>
            {["script", "logs", "parameters"].map(tab => (
              <button key={tab} onClick={() => setDetailTab(tab)} style={{
                padding: "8px 16px",
                background: "transparent", border: "none", cursor: "pointer",
                fontFamily: T.sans, fontSize: 12, fontWeight: 500,
                color: detailTab === tab ? T.amber : T.dim,
                borderBottom: `2px solid ${detailTab === tab ? T.amber : "transparent"}`,
                textTransform: "capitalize",
              }}>{tab}</button>
            ))}
          </div>

          {/* tab content */}
          <div style={{ flex: 1, overflow: "auto", background: T.bg }}>
            {detailTab === "script" && (
              <SlurmScript src={SLURM_SCRIPTS[job.id]} />
            )}

            {detailTab === "logs" && (
              <div style={{ padding: "12px 16px" }}>
                {(LOGS[job.id] ?? ["No log output available."]).map((line, i) => (
                  <div key={i} style={{
                    fontFamily: T.mono, fontSize: 12, lineHeight: 1.7,
                    color: line.includes("error") || line.includes("ERROR") ? T.red
                         : line.includes("done") || line.includes("completed") ? T.green
                         : line.includes("running") ? T.amber
                         : T.muted,
                  }}>{line}</div>
                ))}
              </div>
            )}

            {detailTab === "parameters" && (
              <div style={{ padding: "14px 16px" }}>
                <pre style={{
                  margin: 0, fontFamily: T.mono, fontSize: 12, lineHeight: 1.7, color: T.muted,
                }}>
{`{
  "T_min": 100,
  "T_max": 400,
  "T_steps": 50,
  "N": 1024,
  "replicas": 10,
  "seed": 42,
  "boundary": "periodic",
  "model": "dipole",
  "output_dir": "$SCRATCH/results"
}`}
                </pre>
              </div>
            )}
          </div>

          {/* Fieldnotes link footer */}
          <div style={{
            padding: "10px 16px",
            borderTop: `1px solid ${T.border}`,
            background: T.panel,
            display: "flex", alignItems: "center", justifyContent: "space-between",
          }}>
            <span style={{ fontFamily: T.sans, fontSize: 11, color: T.dim }}>
              Fieldnotes run
            </span>
            {job.id === "15040777" ? (
              <span style={{ fontFamily: T.mono, fontSize: 11, color: "#3D74F6" }}>
                → fn://runs/a3f9c1 ↗
              </span>
            ) : (
              <span style={{ fontFamily: T.mono, fontSize: 11, color: T.vdim }}>not linked</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NotificationsPage() {
  return (
    <div style={{ padding: "28px 32px", maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 4px", fontFamily: T.sans, fontSize: 18, fontWeight: 600, color: T.text }}>
        Notifications
      </h2>
      <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 13, color: T.dim }}>
        ClusterPilot sends notifications via ntfy.sh or any compatible webhook.
      </p>

      {/* ntfy endpoint */}
      <div style={{ marginBottom: 24 }}>
        <label style={{ display: "block", fontFamily: T.sans, fontSize: 12, fontWeight: 600, color: T.muted, marginBottom: 6 }}>
          ntfy.sh topic URL
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input readOnly value="https://ntfy.sh/cp-julia-a8f3k2" style={{
            flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
            borderRadius: 5, padding: "8px 12px",
            fontFamily: T.mono, fontSize: 12, color: T.text,
            outline: "none",
          }} />
          <button style={btnStyle}>Copy</button>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 11, color: T.dim }}>
          Subscribe on any device: <span style={{ fontFamily: T.mono, color: T.muted }}>ntfy subscribe cp-julia-a8f3k2</span>
        </p>
      </div>

      {/* webhook */}
      <div style={{ marginBottom: 28 }}>
        <label style={{ display: "block", fontFamily: T.sans, fontSize: 12, fontWeight: 600, color: T.muted, marginBottom: 6 }}>
          Webhook URL <span style={{ fontFamily: T.sans, fontWeight: 400, color: T.dim }}>(optional, alternative to ntfy)</span>
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input placeholder="https://hooks.slack.com/services/..." style={{
            flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
            borderRadius: 5, padding: "8px 12px",
            fontFamily: T.mono, fontSize: 12, color: T.dim,
            outline: "none",
          }} />
          <button style={btnStyle}>Save</button>
        </div>
      </div>

      {/* event toggles */}
      <div>
        <div style={{ fontFamily: T.sans, fontSize: 12, fontWeight: 600, color: T.muted, marginBottom: 12 }}>
          Send a notification when
        </div>
        {[
          { label: "Job starts running",      sub: "PENDING → RUNNING",              on: true  },
          { label: "Job completes",           sub: "RUNNING → COMPLETED",            on: true  },
          { label: "Job fails",               sub: "RUNNING → FAILED / TIMEOUT",     on: true  },
          { label: "Walltime warning",        sub: "less than 30 minutes remaining",  on: false },
        ].map(item => (
          <div key={item.label} style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            padding: "12px 16px",
            background: T.panel2, border: `1px solid ${T.border}`,
            borderRadius: 6, marginBottom: 8,
          }}>
            <div>
              <div style={{ fontFamily: T.sans, fontSize: 13, color: T.text }}>{item.label}</div>
              <div style={{ fontFamily: T.mono, fontSize: 11, color: T.dim, marginTop: 2 }}>{item.sub}</div>
            </div>
            {/* toggle */}
            <div style={{
              width: 40, height: 22, borderRadius: 11,
              background: item.on ? T.amber : T.border2,
              position: "relative", cursor: "pointer", flexShrink: 0,
              transition: "background 0.2s",
            }}>
              <div style={{
                position: "absolute", top: 3,
                left: item.on ? 20 : 3,
                width: 16, height: 16, borderRadius: "50%",
                background: T.text, transition: "left 0.2s",
              }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AccountPage() {
  return (
    <div style={{ padding: "28px 32px", maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 4px", fontFamily: T.sans, fontSize: 18, fontWeight: 600, color: T.text }}>
        Account
      </h2>
      <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 13, color: T.dim }}>
        julia@institution.ca
      </p>

      {/* managed API key */}
      <Section title="Managed API Key">
        <p style={{ margin: "0 0 12px", fontFamily: T.sans, fontSize: 13, color: T.dim }}>
          ClusterPilot uses this key for SLURM script generation. You do not need your own Anthropic account.
        </p>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{
            flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
            borderRadius: 5, padding: "8px 12px",
            fontFamily: T.mono, fontSize: 12, color: T.dim,
            letterSpacing: "0.1em",
          }}>sk-ant-•••••••••••••••••••••••••••••••••••f3kQ</div>
          <button style={btnStyle}>Rotate</button>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 11, color: T.dim }}>
          Last rotated: never. Rotating issues a new key and invalidates the current one immediately.
        </p>
      </Section>

      {/* subscription */}
      <Section title="Subscription">
        <div style={{
          background: T.panel2, border: `1px solid ${T.border2}`,
          borderRadius: 6, padding: "14px 16px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontFamily: T.sans, fontSize: 14, fontWeight: 600, color: T.text }}>
              Researcher <span style={{ fontFamily: T.mono, fontSize: 12, color: T.amber }}>$7 / month</span>
            </div>
            <div style={{ fontFamily: T.sans, fontSize: 12, color: T.dim, marginTop: 3 }}>
              Renews 29 Apr 2026
            </div>
          </div>
          <button style={btnStyle}>Manage billing ↗</button>
        </div>
      </Section>

      {/* danger zone */}
      <Section title="Danger Zone">
        <div style={{
          background: `${T.red}08`, border: `1px solid ${T.red}33`,
          borderRadius: 6, padding: "14px 16px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontFamily: T.sans, fontSize: 13, fontWeight: 600, color: T.red }}>
              Cancel subscription
            </div>
            <div style={{ fontFamily: T.sans, fontSize: 12, color: T.dim, marginTop: 2 }}>
              Revokes managed API key at period end. Local tool still works.
            </div>
          </div>
          <button style={{
            ...btnStyle,
            background: T.redDim, border: `1px solid ${T.red}66`,
            color: T.red,
          }}>Cancel</button>
        </div>
      </Section>
    </div>
  );
}

// shared section wrapper used in Account page
function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{
        fontFamily: T.sans, fontSize: 12, fontWeight: 600,
        color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em",
        marginBottom: 12, paddingBottom: 8,
        borderBottom: `1px solid ${T.border}`,
      }}>{title}</div>
      {children}
    </div>
  );
}

// shared button style
const btnStyle = {
  background: T.panel2, border: `1px solid ${T.border2}`,
  borderRadius: 5, padding: "8px 14px", cursor: "pointer",
  fontFamily: T.sans, fontSize: 12, fontWeight: 500, color: T.muted,
  whiteSpace: "nowrap",
};

// ── Main Dashboard ────────────────────────────────────────────────────────────
const NAV = [
  { id: "jobs",          icon: "▤", label: "Jobs"          },
  { id: "notifications", icon: "◎", label: "Notifications" },
  { id: "account",       icon: "◈", label: "Account"       },
];

export default function ClusterPilotDashboard() {
  const [activeNav, setActiveNav] = useState("jobs");

  const running = JOBS.filter(j => j.status === "RUNNING").length;
  const pending = JOBS.filter(j => j.status === "PENDING").length;

  return (
    <div style={{
      background: T.bg,
      minHeight: "100vh",
      color: T.text,
      display: "flex",
      flexDirection: "column",
      fontFamily: T.sans,
    }}>

      {/* ── TOPBAR ──────────────────────────────────────────────────────────── */}
      <div style={{
        height: 48,
        background: T.panel,
        borderBottom: `1px solid ${T.border2}`,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "0 20px",
        flexShrink: 0,
      }}>
        <Glow color={T.amber} style={{ fontFamily: T.mono, fontSize: 14, fontWeight: 700, letterSpacing: "0.18em" }}>
          ◈ CLUSTERPILOT
        </Glow>
        <div style={{ display: "flex", alignItems: "center", gap: 10,
          background: T.panel2, border: `1px solid ${T.border2}`,
          borderRadius: 5, padding: "5px 12px",
        }}>
          <Glow color={T.amberDim} style={{ fontFamily: T.mono, fontSize: 11 }}>◈</Glow>
          <span style={{ fontFamily: T.mono, fontSize: 12, color: T.dim }}>julia@institution.ca</span>
        </div>
      </div>

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ── SIDEBAR ─────────────────────────────────────────────────────── */}
        <div style={{
          width: 200,
          background: T.panel,
          borderRight: `1px solid ${T.border2}`,
          display: "flex", flexDirection: "column",
          flexShrink: 0,
          paddingTop: 10,
        }}>

          {/* nav items */}
          {NAV.map(item => {
            const active = item.id === activeNav;
            return (
              <button key={item.id} onClick={() => setActiveNav(item.id)} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 16px",
                background: active ? `${T.amber}0f` : "transparent",
                borderLeft: `2px solid ${active ? T.amber : "transparent"}`,
                border: "none", cursor: "pointer", width: "100%", textAlign: "left",
                color: active ? T.amber : T.dim,
                fontFamily: T.sans, fontSize: 13, fontWeight: active ? 600 : 400,
              }}>
                <span style={{
                  fontFamily: T.mono, fontSize: 12, width: 14, textAlign: "center",
                  ...(active ? { textShadow: `0 0 6px ${T.amber}` } : {}),
                }}>{item.icon}</span>
                {item.label}
              </button>
            );
          })}

          {/* ── CLUSTERS PANEL ──────────────────────────────────────────── */}
          <div style={{
            marginTop: "auto",
            borderTop: `1px solid ${T.border2}`,
            padding: "14px 0 8px",
          }}>
            <SectionLabel>Clusters</SectionLabel>
            {CLUSTERS.map(c => (
              <div key={c.name} style={{
                display: "flex", alignItems: "center",
                padding: "6px 16px", gap: 8,
              }}>
                <Dot color={c.status === "connected" ? T.green : T.red} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: T.mono, fontSize: 12, color: T.muted }}>{c.short}</div>
                  <div style={{ fontFamily: T.mono, fontSize: 10, color: T.dim }}>
                    {c.running > 0
                      ? <><Glow color={T.green} style={{ fontSize: 10 }}>{c.running}</Glow> running</>
                      : c.pending > 0
                      ? <><Glow color={T.amber} style={{ fontSize: 10 }}>{c.pending}</Glow> pending</>
                      : "idle"}
                  </div>
                </div>
                <span style={{ fontFamily: T.mono, fontSize: 9, color: T.border3, textTransform: "uppercase" }}>
                  {c.type}
                </span>
              </div>
            ))}

            {/* running/pending summary */}
            <div style={{
              margin: "10px 16px 0",
              padding: "8px 10px",
              background: T.panel2, borderRadius: 5,
              border: `1px solid ${T.border}`,
              display: "flex", justifyContent: "space-around",
            }}>
              <div style={{ textAlign: "center" }}>
                <Glow color={T.green} style={{ fontFamily: T.mono, fontSize: 16, fontWeight: 700, display: "block" }}>
                  {running}
                </Glow>
                <div style={{ fontFamily: T.sans, fontSize: 10, color: T.dim, marginTop: 1 }}>running</div>
              </div>
              <div style={{ width: 1, background: T.border }} />
              <div style={{ textAlign: "center" }}>
                <Glow color={T.amber} style={{ fontFamily: T.mono, fontSize: 16, fontWeight: 700, display: "block" }}>
                  {pending}
                </Glow>
                <div style={{ fontFamily: T.sans, fontSize: 10, color: T.dim, marginTop: 1 }}>pending</div>
              </div>
            </div>
          </div>
        </div>

        {/* ── MAIN CONTENT ────────────────────────────────────────────────── */}
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>

          {/* page title bar */}
          <div style={{
            padding: "14px 20px",
            borderBottom: `1px solid ${T.border}`,
            background: T.panel,
            flexShrink: 0,
          }}>
            <h1 style={{ margin: 0, fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.text }}>
              {NAV.find(n => n.id === activeNav)?.label}
            </h1>
          </div>

          {/* page content */}
          <div style={{ flex: 1, overflow: "auto", display: "flex" }}>
            {activeNav === "jobs"          && <JobsPage />}
            {activeNav === "notifications" && <NotificationsPage />}
            {activeNav === "account"       && <AccountPage />}
          </div>
        </div>
      </div>
    </div>
  );
}
