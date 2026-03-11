import { useState, useEffect, useRef } from "react";

// ── Phosphor amber terminal palette ──────────────────────────────────────────
const P = {
  bg:       "#0c0a06",
  bg2:      "#111008",
  bg3:      "#171410",
  scanline: "rgba(0,0,0,0.18)",
  border:   "#2a2415",
  border2:  "#3d3520",
  amber:    "#e8a020",
  amberDim: "#7a5010",
  amberLo:  "#3a2808",
  green:    "#6ed86e",
  greenDim: "#2a5a2a",
  red:      "#e05050",
  redDim:   "#5a1a1a",
  cyan:     "#50c8c8",
  cyanDim:  "#1a4a4a",
  white:    "#f0e8d0",
  dim:      "#7a6a50",
  dimmer:   "#3a3020",
  mono:     "'JetBrains Mono', 'Fira Code', monospace",
};

// ── Box drawing helpers ───────────────────────────────────────────────────────
const BOX = { tl:"╔", tr:"╗", bl:"╚", br:"╝", h:"═", v:"║", t:"╦", b:"╩", l:"╠", r:"╣", x:"╬",
              tl2:"┌", tr2:"┐", bl2:"└", br2:"┘", h2:"─", v2:"│", ltee:"├", rtee:"┤" };

// ── Sample data ───────────────────────────────────────────────────────────────
const JOBS = [
  { id: "15042891", name: "mc_sweep_T100_400",   status: "RUNNING",   cluster: "cedar",  partition: "gpu",    gpus: "A100×2", elapsed: "3:42:17", walltime: "8:00:00",  pct: 46,  nodes: "cdr2345", mem: "31.2/32G",  account: "def-mlafond" },
  { id: "15042654", name: "dipole_N1024_equil",  status: "PENDING",   cluster: "narval", partition: "gpu",    gpus: "A100×4", elapsed: "─:──:──", walltime: "12:00:00", pct: 0,   nodes: "─",       mem: "─",         account: "def-mlafond" },
  { id: "15041998", name: "spinwave_k_scan",     status: "RUNNING",   cluster: "cedar",  partition: "gpu",    gpus: "A100×1", elapsed: "1:05:44", walltime: "4:00:00",  pct: 27,  nodes: "cdr2301", mem: "14.8/16G",  account: "def-mlafond" },
  { id: "15040777", name: "mc_equil_run_09",     status: "COMPLETED", cluster: "cedar",  partition: "gpu",    gpus: "A100×2", elapsed: "5:11:03", walltime: "6:00:00",  pct: 100, nodes: "cdr2298", mem: "32.0/32G",  account: "def-mlafond" },
  { id: "15039450", name: "benchmark_N128",      status: "FAILED",    cluster: "narval", partition: "gpu",    gpus: "A100×1", elapsed: "0:03:12", walltime: "1:00:00",  pct: 5,   nodes: "ng10042", mem: "4.1/8G",    account: "def-mlafond" },
];

const LOG_LINES = {
  "15042891": [
    "[ 0.00s] SpinGlassLab v2.1.4 initialising",
    "[ 0.12s] CUDA device: NVIDIA A100-SXM4-80GB (×2)",
    "[ 0.13s] Loading assembly: N=1024, periodic BCs",
    "[ 0.41s] Dipole interaction tensor computed",
    "[ 0.42s] Starting sweep: T ∈ [100K, 400K], 50 steps",
    "[ 0.43s] Replica 1/10 │ T=100K │ seed=42",
    "[892.3s] T=100K done  │ <M>=0.9821 │ χ=0.0031",
    "[1847s] T=108K done  │ <M>=0.9744 │ χ=0.0038",
    "[2891s] T=116K done  │ <M>=0.9601 │ χ=0.0052",
    "[3744s] T=124K done  │ <M>=0.9389 │ χ=0.0079",
    "[4601s] T=132K done  │ <M>=0.9104 │ χ=0.0118",
    "[5512s] T=140K done  │ <M>=0.8751 │ χ=0.0181",
    "[6489s] T=148K done  │ <M>=0.8244 │ χ=0.0294",
    "[7401s] T=156K ──── currently running ────",
  ],
  "15040777": [
    "[ 0.00s] SpinGlassLab v2.1.4 initialising",
    "[ 0.11s] CUDA device: NVIDIA A100-SXM4-80GB (×2)",
    "[ 0.39s] Dipole interaction tensor computed",
    "[1204s] All temperatures completed",
    "[1204s] Writing output: mc_equil_run_09_results.h5",
    "[1205s] Checksum OK",
    "[1205s] Job completed successfully ✓",
  ],
  "15039450": [
    "[ 0.00s] SpinGlassLab v2.1.4 initialising",
    "[ 0.11s] CUDA device: NVIDIA A100-SXM4-40GB (×1)",
    "[ 0.38s] Loading assembly: N=128",
    "[192.1s] CUDA error: device-side assert triggered",
    "[192.1s] in kernel dipole_field_kernel at line 447",
    "[192.1s] ERROR: Job terminated with exit code 1",
  ],
  "15041998": [
    "[ 0.00s] SpinGlassLab v2.1.4 initialising",
    "[ 0.12s] CUDA device: NVIDIA A100-SXM4-80GB (×1)",
    "[ 0.40s] k-space scan: 512 wavevectors",
    "[1200s] k-point 128/512 complete",
    "[2401s] k-point 256/512 complete ──── running ────",
  ],
};

const STATUS_COLOR = {
  RUNNING:   { fg: P.green,  bg: P.greenDim, char: "▶" },
  PENDING:   { fg: P.amber,  bg: P.amberLo,  char: "◈" },
  COMPLETED: { fg: P.cyan,   bg: P.cyanDim,  char: "✓" },
  FAILED:    { fg: P.red,    bg: P.redDim,   char: "✗" },
};

// ── Reusable primitives ───────────────────────────────────────────────────────
function Glow({ color = P.amber, children, style = {} }) {
  return (
    <span style={{ color, textShadow: `0 0 8px ${color}88, 0 0 2px ${color}`, ...style }}>
      {children}
    </span>
  );
}

function Badge({ status }) {
  const c = STATUS_COLOR[status] || STATUS_COLOR.PENDING;
  return (
    <span style={{
      fontFamily: P.mono, fontSize: 10, fontWeight: 700,
      color: c.fg, background: c.bg,
      border: `1px solid ${c.fg}44`,
      borderRadius: 2, padding: "0 5px",
      textShadow: `0 0 6px ${c.fg}88`,
    }}>{c.char} {status}</span>
  );
}

function ProgressBar({ pct, color = P.green, width = 20 }) {
  const filled = Math.round(pct / 100 * width);
  const empty = width - filled;
  return (
    <span style={{ fontFamily: P.mono, fontSize: 11, color }}>
      <span style={{ textShadow: `0 0 4px ${color}` }}>{"█".repeat(filled)}</span>
      <span style={{ color: P.dimmer }}>{"░".repeat(empty)}</span>
      <span style={{ color: P.dim, marginLeft: 4 }}>{pct}%</span>
    </span>
  );
}

function PanelBorder({ title, color = P.amberDim, titleColor = P.amber, children, style = {} }) {
  return (
    <div style={{
      border: `1px solid ${color}`,
      boxShadow: `inset 0 0 30px rgba(0,0,0,0.3), 0 0 8px ${color}22`,
      position: "relative", ...style,
    }}>
      {title && (
        <div style={{
          position: "absolute", top: -9, left: 12,
          background: P.bg, padding: "0 6px",
          fontFamily: P.mono, fontSize: 10, fontWeight: 700,
          color: titleColor, letterSpacing: "0.1em",
          textShadow: `0 0 8px ${titleColor}`,
        }}>{title}</div>
      )}
      {children}
    </div>
  );
}

// ── Main TUI app ──────────────────────────────────────────────────────────────
export default function ClusterPilotTUI() {
  const [selectedJob, setSelectedJob] = useState(0);
  const [activeView, setActiveView] = useState("jobs");  // jobs | submit | config
  const [submitText, setSubmitText] = useState("");
  const [generatedScript, setGeneratedScript] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);
  const [notification, setNotification] = useState(null);
  const [tick, setTick] = useState(0);
  const logRef = useRef(null);

  // Clock tick for blinking cursor and elapsed time animation
  useEffect(() => {
    const t = setInterval(() => setTick(n => n + 1), 800);
    return () => clearInterval(t);
  }, []);

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [selectedJob]);

  const job = JOBS[selectedJob];
  const sc = STATUS_COLOR[job.status];

  function showNotif(msg, color = P.green) {
    setNotification({ msg, color });
    setTimeout(() => setNotification(null), 3000);
  }

  function handleGenerate() {
    if (!submitText.trim()) return;
    setIsGenerating(true);
    setGeneratedScript("");
    const script = `#!/bin/bash
#SBATCH --job-name=${submitText.split(" ")[0].toLowerCase().replace(/[^a-z0-9]/g,"_")}
#SBATCH --account=def-mlafond
#SBATCH --gres=gpu:a100:2
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=08:00:00
#SBATCH --output=%x-%j.out
#SBATCH --mail-type=FAIL,END
#SBATCH --mail-user=julia@example.ca

module load julia/1.10.4 cuda/12.2

cd $SCRATCH/clusterpilot_jobs/$SLURM_JOB_NAME

julia --project=. run_simulation.jl \\
  --config config.toml \\
  --output $SCRATCH/results/$SLURM_JOB_ID`;

    let i = 0;
    const chars = script.split("");
    const interval = setInterval(() => {
      i += 3;
      setGeneratedScript(chars.slice(0, i).join(""));
      if (i >= chars.length) { clearInterval(interval); setIsGenerating(false); }
    }, 12);
  }

  const cursorChar = tick % 2 === 0 ? "█" : " ";

  return (
    <div style={{
      background: P.bg,
      minHeight: "100vh",
      fontFamily: P.mono,
      color: P.white,
      display: "flex",
      flexDirection: "column",
      position: "relative",
      overflow: "hidden",
    }}>

      {/* Scanline overlay */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 100,
        background: `repeating-linear-gradient(0deg, transparent, transparent 2px, ${P.scanline} 2px, ${P.scanline} 4px)`,
      }} />

      {/* Vignette */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 99,
        background: "radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.5) 100%)",
      }} />

      {/* ── TITLEBAR ─────────────────────────────────────────────────────── */}
      <div style={{
        background: P.bg3,
        borderBottom: `1px solid ${P.border2}`,
        padding: "4px 14px",
        display: "flex", alignItems: "center", justifyContent: "space-between",
        boxShadow: `0 2px 12px rgba(0,0,0,0.5)`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <Glow color={P.amber} style={{ fontSize: 13, fontWeight: 700, letterSpacing: "0.2em" }}>
            ◈ CLUSTERPILOT
          </Glow>
          <span style={{ color: P.dim, fontSize: 10 }}>v0.1.0-dev</span>
          <span style={{ color: P.border2 }}>│</span>
          <span style={{ color: P.dim, fontSize: 10 }}>
            <Glow color={P.green} style={{ fontSize: 10 }}>●</Glow>
            {" "}cedar.computecanada.ca
          </span>
          <span style={{ color: P.dim, fontSize: 10 }}>
            <Glow color={P.amber} style={{ fontSize: 10 }}>●</Glow>
            {" "}narval.computecanada.ca
          </span>
        </div>
        <div style={{ display: "flex", gap: 18, alignItems: "center" }}>
          <span style={{ color: P.dim, fontSize: 10 }}>
            JOBS: <Glow color={P.amber} style={{ fontSize: 10 }}>5</Glow>
            {"  "}RUNNING: <Glow color={P.green} style={{ fontSize: 10 }}>2</Glow>
          </span>
          <span style={{ color: P.dim, fontSize: 10 }}>
            {new Date().toLocaleTimeString("en-CA", { hour12: false })}
          </span>
        </div>
      </div>

      {/* ── NAV TABS ──────────────────────────────────────────────────────── */}
      <div style={{
        background: P.bg2,
        borderBottom: `1px solid ${P.border}`,
        padding: "0 14px",
        display: "flex", gap: 0,
      }}>
        {[
          { id: "jobs",   label: " F1 JOBS   " },
          { id: "submit", label: " F2 SUBMIT " },
          { id: "config", label: " F9 CONFIG " },
        ].map(tab => (
          <button key={tab.id} onClick={() => setActiveView(tab.id)} style={{
            background: activeView === tab.id ? P.bg3 : "transparent",
            border: "none",
            borderRight: `1px solid ${P.border}`,
            borderBottom: activeView === tab.id ? `2px solid ${P.amber}` : `2px solid transparent`,
            color: activeView === tab.id ? P.amber : P.dim,
            fontFamily: P.mono, fontSize: 11,
            padding: "5px 0",
            cursor: "pointer",
            textShadow: activeView === tab.id ? `0 0 8px ${P.amber}` : "none",
            letterSpacing: "0.05em",
            minWidth: 100, textAlign: "center",
          }}>{tab.label}</button>
        ))}
      </div>

      {/* ── BODY ─────────────────────────────────────────────────────────── */}
      <div style={{ flex: 1, display: "flex", gap: 0, overflow: "hidden", padding: 10, gap: 8 }}>

        {activeView === "jobs" && (
          <>
            {/* ── LEFT: JOB LIST ──────────────────────────────────────── */}
            <PanelBorder title="═ QUEUE " style={{ width: 280, flexShrink: 0, display: "flex", flexDirection: "column" }}>
              <div style={{ overflowY: "auto", flex: 1 }}>
                {JOBS.map((j, i) => {
                  const c = STATUS_COLOR[j.status];
                  const active = i === selectedJob;
                  return (
                    <div key={j.id} onClick={() => setSelectedJob(i)} style={{
                      padding: "7px 10px",
                      background: active ? `${P.amberLo}` : "transparent",
                      borderLeft: `3px solid ${active ? P.amber : "transparent"}`,
                      borderBottom: `1px solid ${P.border}`,
                      cursor: "pointer",
                      transition: "background 0.1s",
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                        <span style={{
                          fontSize: 11, fontWeight: 700,
                          color: active ? P.amber : P.white,
                          textShadow: active ? `0 0 8px ${P.amber}` : "none",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          maxWidth: 155,
                        }}>{j.name}</span>
                        <span style={{
                          fontSize: 9, color: c.fg,
                          textShadow: `0 0 4px ${c.fg}88`,
                        }}>{c.char}</span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between" }}>
                        <span style={{ fontSize: 9, color: P.dim }}>#{j.id.slice(-6)}</span>
                        <span style={{ fontSize: 9, color: P.dim }}>{j.cluster}</span>
                      </div>
                      {j.status === "RUNNING" && (
                        <div style={{ marginTop: 4 }}>
                          <ProgressBar pct={j.pct} width={24} />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </PanelBorder>

            {/* ── RIGHT: JOB DETAIL ───────────────────────────────────── */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8, minWidth: 0 }}>

              {/* Detail header */}
              <PanelBorder title={`═ JOB ${job.id} `} style={{ padding: "10px 14px" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "8px 24px" }}>
                  {[
                    ["NAME",    <Glow color={P.amber}>{job.name}</Glow>],
                    ["STATUS",  <Badge status={job.status} />],
                    ["CLUSTER", <Glow color={P.cyan}>{job.cluster}</Glow>],
                    ["GPUs",    job.gpus],
                    ["ELAPSED", <Glow color={job.status==="RUNNING"?P.green:P.dim}>{job.elapsed}</Glow>],
                    ["LIMIT",   job.walltime],
                    ["NODES",   job.nodes],
                    ["MEMORY",  job.mem],
                    ["ACCOUNT", job.account],
                  ].map(([k, v]) => (
                    <div key={k} style={{ minWidth: 120 }}>
                      <div style={{ fontSize: 9, color: P.dim, marginBottom: 1, letterSpacing: "0.1em" }}>{k}</div>
                      <div style={{ fontSize: 11 }}>{v}</div>
                    </div>
                  ))}
                </div>
                {job.status === "RUNNING" && (
                  <div style={{ marginTop: 10 }}>
                    <div style={{ fontSize: 9, color: P.dim, marginBottom: 3, letterSpacing: "0.1em" }}>WALLTIME PROGRESS</div>
                    <ProgressBar pct={job.pct} width={60} color={P.green} />
                  </div>
                )}
              </PanelBorder>

              {/* Log output */}
              <PanelBorder title="═ OUTPUT LOG " style={{ flex: 1, display: "flex", flexDirection: "column" }}>
                <div ref={logRef} style={{
                  flex: 1, overflowY: "auto", padding: "8px 12px",
                  maxHeight: 220,
                }}>
                  {(LOG_LINES[job.id] || ["No output available."]).map((line, i) => {
                    const isErr = line.includes("ERROR") || line.includes("error") || line.includes("FAIL");
                    const isOk  = line.includes("✓") || line.includes("successfully");
                    const isWarn= line.includes("running ────");
                    const isLast = i === (LOG_LINES[job.id]||[]).length - 1;
                    return (
                      <div key={i} style={{
                        fontSize: 11, lineHeight: "1.7",
                        color: isErr ? P.red : isOk ? P.cyan : isWarn ? P.amber : P.white,
                        textShadow: isErr ? `0 0 6px ${P.red}66` : isOk ? `0 0 6px ${P.cyan}66` : "none",
                      }}>
                        {line}{isLast && job.status === "RUNNING" ? <span style={{ color: P.green }}>{cursorChar}</span> : ""}
                      </div>
                    );
                  })}
                </div>
              </PanelBorder>

              {/* Action bar */}
              <div style={{ display: "flex", gap: 8 }}>
                {[
                  { label: "  [R] RSYNC NOW  ", color: P.cyan,  act: () => showNotif("rsync started → ./results/" + job.id + "/", P.cyan)  },
                  { label: "  [K] KILL JOB   ", color: P.red,   act: () => showNotif("scancel " + job.id + " submitted", P.red),
                    disabled: job.status !== "RUNNING" && job.status !== "PENDING" },
                  { label: "  [T] TAIL LOG   ", color: P.amber, act: () => showNotif("tailing slurm-" + job.id + ".out…", P.amber)          },
                  { label: "  [N] NTFY TEST  ", color: P.green, act: () => showNotif("📱 test push sent to ntfy.sh", P.green)               },
                ].map(btn => (
                  <button key={btn.label} onClick={btn.act} disabled={btn.disabled} style={{
                    background: btn.disabled ? P.dimmer : P.bg3,
                    border: `1px solid ${btn.disabled ? P.border : btn.color + "66"}`,
                    color: btn.disabled ? P.dimmer : btn.color,
                    fontFamily: P.mono, fontSize: 11,
                    padding: "5px 0", flex: 1,
                    cursor: btn.disabled ? "not-allowed" : "pointer",
                    textShadow: btn.disabled ? "none" : `0 0 8px ${btn.color}66`,
                    letterSpacing: "0.05em",
                  }}>{btn.label}</button>
                ))}
              </div>
            </div>
          </>
        )}

        {activeView === "submit" && (
          <div style={{ flex: 1, display: "flex", gap: 8 }}>
            {/* Left: prompt input */}
            <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 8 }}>
              <PanelBorder title="═ DESCRIBE YOUR JOB " style={{ padding: 12, flex: "0 0 auto" }}>
                <div style={{ fontSize: 9, color: P.dim, marginBottom: 6, letterSpacing: "0.1em" }}>
                  PLAIN LANGUAGE → AI GENERATES SLURM SCRIPT
                </div>
                <div style={{
                  background: P.bg3, border: `1px solid ${P.border2}`,
                  padding: "8px 10px", minHeight: 60,
                  fontSize: 12, color: P.white, lineHeight: 1.6,
                  position: "relative",
                }}>
                  <span style={{ color: P.dim }}>▶ </span>
                  {submitText}
                  <span style={{ color: P.green }}>{cursorChar}</span>
                  {!submitText && (
                    <span style={{ color: P.dimmer, position: "absolute", top: 8, left: 26, pointerEvents: "none" }}>
                      e.g. "MC sweep T=100-400K, N=2048, 10 replicas, ~8h on 2 A100s"
                    </span>
                  )}
                </div>
                <textarea
                  value={submitText}
                  onChange={e => setSubmitText(e.target.value)}
                  placeholder=""
                  style={{
                    position: "absolute", opacity: 0, pointerEvents: submitText !== undefined ? "auto" : "none",
                    width: "100%", height: "100%",
                  }}
                />
                <div style={{ marginTop: 8, display: "flex", gap: 8, alignItems: "center" }}>
                  <div style={{ flex: 1, fontSize: 9, color: P.dim }}>
                    TARGET: <Glow color={P.cyan} style={{ fontSize: 9 }}>cedar</Glow>
                    {"  "}ACCOUNT: <Glow color={P.amber} style={{ fontSize: 9 }}>def-mlafond</Glow>
                  </div>
                  <button onClick={handleGenerate} disabled={isGenerating} style={{
                    background: isGenerating ? P.amberLo : P.amberDim,
                    border: `1px solid ${P.amber}`,
                    color: P.amber,
                    fontFamily: P.mono, fontSize: 11, padding: "4px 16px",
                    cursor: isGenerating ? "wait" : "pointer",
                    textShadow: `0 0 8px ${P.amber}`,
                    letterSpacing: "0.08em",
                  }}>
                    {isGenerating ? "GENERATING…" : "⚙ GENERATE SCRIPT"}
                  </button>
                </div>
              </PanelBorder>

              {/* File sync */}
              <PanelBorder title="═ FILES TO UPLOAD " style={{ padding: 12 }}>
                {["run_sweep.jl", "Project.toml", "Manifest.toml", "config.toml"].map((f, i) => (
                  <div key={f} style={{
                    display: "flex", alignItems: "center", gap: 8,
                    padding: "3px 0", borderBottom: `1px solid ${P.border}`,
                    fontSize: 11,
                  }}>
                    <Glow color={P.green} style={{ fontSize: 10 }}>✓</Glow>
                    <span style={{ color: P.white }}>{f}</span>
                    <span style={{ color: P.dim, marginLeft: "auto", fontSize: 10 }}>
                      {["4.2 KB", "1.1 KB", "18.4 KB", "0.8 KB"][i]}
                    </span>
                  </div>
                ))}
                <div style={{ marginTop: 6, fontSize: 10, color: P.dim }}>
                  DEST: <span style={{ color: P.cyan }}>$SCRATCH/clusterpilot_jobs/&lt;jobname&gt;/</span>
                </div>
              </PanelBorder>

              {/* Notification prefs */}
              <PanelBorder title="═ NOTIFY ON " style={{ padding: "8px 12px" }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px 16px" }}>
                  {[
                    ["STARTED",   true,  P.cyan],
                    ["COMPLETED", true,  P.green],
                    ["FAILED",    true,  P.red],
                    ["ETA-30MIN", true,  P.amber],
                    ["LOW-TIME",  false, P.amber],
                  ].map(([label, on, color]) => (
                    <div key={label} style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 10 }}>
                      <span style={{
                        display: "inline-block", width: 22, height: 11, borderRadius: 6,
                        background: on ? color + "44" : P.dimmer,
                        border: `1px solid ${on ? color : P.border}`,
                        position: "relative",
                      }}>
                        <span style={{
                          position: "absolute", top: 1.5, width: 7, height: 7, borderRadius: "50%",
                          background: on ? color : P.dim,
                          left: on ? 13 : 2,
                          boxShadow: on ? `0 0 4px ${color}` : "none",
                          transition: "left 0.2s",
                        }} />
                      </span>
                      <span style={{ color: on ? P.white : P.dim }}>{label}</span>
                    </div>
                  ))}
                  <span style={{ marginLeft: "auto", fontSize: 9, color: P.dim }}>
                    via <Glow color={P.amber} style={{ fontSize: 9 }}>ntfy.sh/julia-hpc-abc123</Glow>
                  </span>
                </div>
              </PanelBorder>
            </div>

            {/* Right: generated script */}
            <PanelBorder title="═ GENERATED SLURM SCRIPT " style={{ flex: 1, display: "flex", flexDirection: "column" }}>
              <div style={{
                flex: 1, padding: "8px 12px", overflowY: "auto",
                fontSize: 11, lineHeight: 1.8,
              }}>
                {generatedScript ? (
                  generatedScript.split("\n").map((line, i) => {
                    const isSbatch  = line.startsWith("#SBATCH");
                    const isComment = line.startsWith("#") && !isSbatch;
                    const isModule  = line.startsWith("module");
                    const isCmd     = line.startsWith("julia") || line.startsWith("python");
                    return (
                      <div key={i} style={{
                        color: isSbatch ? P.amber : isComment ? P.dim : isModule ? P.cyan : isCmd ? P.green : P.white,
                        textShadow: isSbatch ? `0 0 6px ${P.amber}44` : isCmd ? `0 0 6px ${P.green}44` : "none",
                        whiteSpace: "pre",
                      }}>{line || " "}</div>
                    );
                  })
                ) : (
                  <div style={{ color: P.dimmer, fontSize: 11 }}>
                    {[
                      "Describe your job on the left,",
                      "then press [GENERATE SCRIPT].",
                      "",
                      "ClusterPilot will query:",
                      "  sinfo     → available partitions",
                      "  module avail → installed software",
                      "  sacctmgr  → your account limits",
                      "",
                      "…and generate a correct SLURM",
                      "script for this specific cluster.",
                    ].map((l, i) => <div key={i}>{l || <br />}</div>)}
                  </div>
                )}
                {isGenerating && <span style={{ color: P.green }}>{cursorChar}</span>}
              </div>
              {generatedScript && !isGenerating && (
                <div style={{ padding: "8px 12px", borderTop: `1px solid ${P.border}`, display: "flex", gap: 8 }}>
                  <button onClick={() => showNotif("rsync + sbatch submitted → job queued", P.green)} style={{
                    flex: 2, background: P.greenDim, border: `1px solid ${P.green}`,
                    color: P.green, fontFamily: P.mono, fontSize: 11, padding: "5px",
                    cursor: "pointer", textShadow: `0 0 8px ${P.green}`,
                    letterSpacing: "0.05em",
                  }}>⚡ UPLOAD + SUBMIT</button>
                  <button onClick={() => showNotif("script saved to ./scripts/", P.amber)} style={{
                    flex: 1, background: P.bg3, border: `1px solid ${P.amberDim}`,
                    color: P.amber, fontFamily: P.mono, fontSize: 11, padding: "5px",
                    cursor: "pointer",
                  }}>⬇ SAVE</button>
                  <button onClick={() => { setGeneratedScript(""); setSubmitText(""); }} style={{
                    flex: 1, background: P.bg3, border: `1px solid ${P.border2}`,
                    color: P.dim, fontFamily: P.mono, fontSize: 11, padding: "5px",
                    cursor: "pointer",
                  }}>✕ CLEAR</button>
                </div>
              )}
            </PanelBorder>
          </div>
        )}

        {activeView === "config" && (
          <PanelBorder title="═ CONFIGURATION " style={{ flex: 1, padding: 16 }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {[
                { section: "CLUSTER PROFILES", items: [
                  ["cedar.computecanada.ca", "julianfrank → def-mlafond", P.green],
                  ["narval.computecanada.ca", "julianfrank → def-mlafond", P.green],
                ]},
                { section: "SSH CONFIG", items: [
                  ["ControlMaster", "auto", P.cyan],
                  ["ControlPersist", "4h", P.cyan],
                  ["ControlPath", "~/.ssh/cm_%h_%p_%r", P.cyan],
                ]},
                { section: "NOTIFICATIONS", items: [
                  ["ntfy.sh topic", "julia-hpc-abc123", P.amber],
                  ["Poll interval", "5 min", P.amber],
                ]},
                { section: "AI SCRIPT GENERATION", items: [
                  ["Model", "claude-sonnet-4-6", P.purple || P.amber],
                  ["API key", "sk-ant-***…***", P.dim],
                ]},
              ].map(({ section, items }) => (
                <div key={section}>
                  <div style={{ color: P.amberDim, fontSize: 9, letterSpacing: "0.15em", marginBottom: 6, borderBottom: `1px solid ${P.border}`, paddingBottom: 3 }}>{section}</div>
                  {items.map(([k, v, color]) => (
                    <div key={k} style={{ display: "flex", gap: 8, padding: "3px 0", fontSize: 11 }}>
                      <span style={{ color: P.dim, minWidth: 180 }}>{k}</span>
                      <span style={{ color: color || P.white }}>{v}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </PanelBorder>
        )}
      </div>

      {/* ── STATUS BAR ──────────────────────────────────────────────────────── */}
      <div style={{
        background: P.amberLo,
        borderTop: `1px solid ${P.amberDim}`,
        padding: "3px 14px",
        display: "flex", justifyContent: "space-between",
        fontSize: 9, color: P.amberDim, letterSpacing: "0.08em",
      }}>
        <div style={{ display: "flex", gap: 16 }}>
          <span><Glow color={P.amber} style={{ fontSize: 9 }}>F1</Glow> JOBS</span>
          <span><Glow color={P.amber} style={{ fontSize: 9 }}>F2</Glow> SUBMIT</span>
          <span><Glow color={P.amber} style={{ fontSize: 9 }}>F9</Glow> CONFIG</span>
          <span><Glow color={P.amber} style={{ fontSize: 9 }}>Q</Glow> QUIT</span>
          <span><Glow color={P.amber} style={{ fontSize: 9 }}>↑↓</Glow> SELECT</span>
          <span><Glow color={P.amber} style={{ fontSize: 9 }}>ENTER</Glow> DETAIL</span>
        </div>
        <div style={{ display: "flex", gap: 16 }}>
          <span>POLL: <Glow color={P.green} style={{ fontSize: 9 }}>ACTIVE</Glow></span>
          <span>DAEMON: <Glow color={P.green} style={{ fontSize: 9 }}>RUNNING</Glow></span>
          <span style={{ color: P.dim }}>clusterpilot-poll.service</span>
        </div>
      </div>

      {/* ── NOTIFICATION TOAST ──────────────────────────────────────────────── */}
      {notification && (
        <div style={{
          position: "fixed", bottom: 36, right: 20, zIndex: 200,
          background: P.bg3, border: `1px solid ${notification.color}`,
          padding: "8px 16px", fontSize: 11,
          color: notification.color,
          textShadow: `0 0 8px ${notification.color}`,
          boxShadow: `0 0 20px ${notification.color}44`,
          animation: "fadeIn 0.2s ease",
          fontFamily: P.mono,
        }}>
          ◈ {notification.msg}
        </div>
      )}

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: ${P.bg}; }
        ::-webkit-scrollbar-thumb { background: ${P.amberDim}; border-radius: 2px; }
        ::-webkit-scrollbar-thumb:hover { background: ${P.amber}; }
        textarea { resize: none; outline: none; }
        @keyframes fadeIn { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
        button:hover:not(:disabled) { filter: brightness(1.25); }
      `}</style>
    </div>
  );
}
