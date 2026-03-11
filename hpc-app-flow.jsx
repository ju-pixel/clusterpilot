import { useState } from "react";

const COLORS = {
  bg: "#0a0e14",
  panel: "#0f1520",
  border: "#1a2535",
  borderBright: "#2a3f5f",
  green: "#4ade80",
  greenDim: "#166534",
  amber: "#fbbf24",
  amberDim: "#78350f",
  blue: "#60a5fa",
  blueDim: "#1e3a5f",
  red: "#f87171",
  redDim: "#7f1d1d",
  purple: "#a78bfa",
  purpleDim: "#3b1f6e",
  text: "#c9d4e8",
  textDim: "#5a6a85",
  textBright: "#e8f0ff",
  mono: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
  sans: "'DM Sans', 'Segoe UI', sans-serif",
};

const style = (css) => ({ style: css });

function Tag({ color, children }) {
  const colors = {
    green: { bg: COLORS.greenDim, text: COLORS.green, border: "#22c55e44" },
    amber: { bg: COLORS.amberDim, text: COLORS.amber, border: "#f59e0b44" },
    blue: { bg: COLORS.blueDim, text: COLORS.blue, border: "#3b82f644" },
    red: { bg: COLORS.redDim, text: COLORS.red, border: "#ef444444" },
    purple: { bg: COLORS.purpleDim, text: COLORS.purple, border: "#8b5cf644" },
  };
  const c = colors[color] || colors.blue;
  return (
    <span style={{
      background: c.bg, color: c.text, border: `1px solid ${c.border}`,
      borderRadius: 4, padding: "1px 7px", fontSize: 10, fontFamily: COLORS.mono,
      letterSpacing: "0.05em", fontWeight: 600, whiteSpace: "nowrap",
    }}>{children}</span>
  );
}

function Arrow({ vertical, color = COLORS.textDim, label }) {
  if (vertical) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, margin: "2px 0" }}>
      {label && <span style={{ fontSize: 9, color: COLORS.textDim, fontFamily: COLORS.mono, letterSpacing: "0.05em" }}>{label}</span>}
      <div style={{ width: 1, height: 18, background: `linear-gradient(to bottom, transparent, ${color}, transparent)` }} />
      <div style={{ width: 0, height: 0, borderLeft: "4px solid transparent", borderRight: "4px solid transparent", borderTop: `6px solid ${color}` }} />
    </div>
  );
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 2 }}>
      <div style={{ height: 1, width: 24, background: `linear-gradient(to right, transparent, ${color})` }} />
      <div style={{ width: 0, height: 0, borderTop: "4px solid transparent", borderBottom: "4px solid transparent", borderLeft: `6px solid ${color}` }} />
    </div>
  );
}

function Box({ title, items, color = "blue", icon, subtitle, wide }) {
  const c = {
    green: { border: COLORS.greenDim, accent: COLORS.green, glow: "#4ade8022" },
    amber: { border: COLORS.amberDim, accent: COLORS.amber, glow: "#fbbf2422" },
    blue: { border: COLORS.blueDim, accent: COLORS.blue, glow: "#60a5fa22" },
    red: { border: COLORS.redDim, accent: COLORS.red, glow: "#f8717122" },
    purple: { border: COLORS.purpleDim, accent: COLORS.purple, glow: "#a78bfa22" },
  }[color];

  return (
    <div style={{
      background: COLORS.panel, border: `1px solid ${c.border}`,
      borderTop: `2px solid ${c.accent}`, borderRadius: 8,
      padding: "10px 14px", minWidth: wide ? 220 : 160,
      boxShadow: `0 0 20px ${c.glow}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        {icon && <span style={{ fontSize: 14 }}>{icon}</span>}
        <span style={{ color: c.accent, fontFamily: COLORS.mono, fontSize: 11, fontWeight: 700, letterSpacing: "0.08em" }}>{title}</span>
      </div>
      {subtitle && <div style={{ color: COLORS.textDim, fontSize: 10, fontFamily: COLORS.mono, marginBottom: 6 }}>{subtitle}</div>}
      {items && items.map((item, i) => (
        <div key={i} style={{ color: COLORS.text, fontSize: 10, fontFamily: COLORS.mono, padding: "2px 0", borderBottom: i < items.length - 1 ? `1px solid ${COLORS.border}` : "none", lineHeight: 1.5 }}>
          <span style={{ color: c.accent, marginRight: 5 }}>›</span>{item}
        </div>
      ))}
    </div>
  );
}

function SectionLabel({ children }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "8px 0 4px" }}>
      <div style={{ flex: 1, height: 1, background: COLORS.border }} />
      <span style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 9, letterSpacing: "0.15em", textTransform: "uppercase" }}>{children}</span>
      <div style={{ flex: 1, height: 1, background: COLORS.border }} />
    </div>
  );
}

function FlowTab() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 0, padding: "0 4px" }}>

      {/* ROW 1: User action */}
      <SectionLabel>User Initiates Job</SectionLabel>
      <div style={{ display: "flex", justifyContent: "center" }}>
        <Box icon="🖥️" title="LOCAL WORKSTATION" color="blue" subtitle="Fedora 42 / macOS"
          items={["Open ClusterPilot UI", "Select project directory", "Choose target cluster", "Describe job in plain language"]} wide />
      </div>

      <Arrow vertical color={COLORS.blue} />

      {/* ROW 2: App processes */}
      <SectionLabel>App Intelligence Layer</SectionLabel>
      <div style={{ display: "flex", justifyContent: "center", gap: 20, flexWrap: "wrap" }}>
        <Box icon="🔐" title="AUTH MODULE" color="amber"
          items={["SSH key lookup", "ControlMaster socket", "One-time MFA prompt", "Persist session"]} />
        <Arrow color={COLORS.amber} />
        <Box icon="🔍" title="CLUSTER PROBE" color="amber"
          items={["sinfo → partitions", "module avail → env", "sacctmgr → account", "Cache results 24h"]} />
        <Arrow color={COLORS.amber} />
        <Box icon="🤖" title="AI SCRIPT GEN" color="purple"
          items={["Context: cluster spec", "Context: job type", "Generate SLURM script", "User reviews + edits"]} />
      </div>

      <Arrow vertical color={COLORS.purple} />

      {/* ROW 3: Transfer and submit */}
      <SectionLabel>Upload + Submit</SectionLabel>
      <div style={{ display: "flex", justifyContent: "center", gap: 20, flexWrap: "wrap" }}>
        <Box icon="📤" title="FILE SYNC" color="green"
          items={["rsync over SSH", "$SCRATCH/jobname/", "Input files + script", "Verify checksums"]} />
        <Arrow color={COLORS.green} />
        <Box icon="📋" title="JOB SUBMIT" color="green"
          items={["sbatch script.sh", "Capture job ID", "Log to local DB", "Start daemon watch"]} />
      </div>

      <Arrow vertical color={COLORS.green} label="job running on cluster (hours/days)" />

      {/* ROW 4: Daemon - KEY section */}
      <SectionLabel>Background Daemon (no persistent SSH needed)</SectionLabel>
      <div style={{ display: "flex", justifyContent: "center" }}>
        <div style={{
          background: COLORS.panel, border: `1px solid ${COLORS.borderBright}`,
          borderTop: `2px solid ${COLORS.amber}`, borderRadius: 8, padding: "12px 18px",
          boxShadow: `0 0 24px #fbbf2418`, maxWidth: 540, width: "100%",
        }}>
          <div style={{ color: COLORS.amber, fontFamily: COLORS.mono, fontSize: 11, fontWeight: 700, marginBottom: 8, letterSpacing: "0.08em" }}>
            ⚡ POLL DAEMON — systemd user service (workstation-side)
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {[
              { label: "Every 5 min", detail: "short SSH connect → squeue -j JOB_ID → disconnect" },
              { label: "On RUNNING", detail: "estimate ETA from --time vs elapsed, notify phone" },
              { label: "On COMPLETED", detail: "trigger rsync pull from $SCRATCH → local output dir" },
              { label: "On FAILED", detail: "fetch slurm-JOB.out tail, notify with error excerpt" },
            ].map((item, i) => (
              <div key={i} style={{
                background: "#0a0e14", border: `1px solid ${COLORS.border}`, borderRadius: 6,
                padding: "6px 10px", flex: "1 1 220px",
              }}>
                <div style={{ color: COLORS.amber, fontFamily: COLORS.mono, fontSize: 10, fontWeight: 700 }}>{item.label}</div>
                <div style={{ color: COLORS.text, fontFamily: COLORS.mono, fontSize: 10, marginTop: 2, lineHeight: 1.5 }}>{item.detail}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 8, color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 10, lineHeight: 1.6 }}>
            💡 No persistent connection. Each poll opens a new SSH connection via the existing ControlMaster socket (sub-second reconnect),
            runs one command, and closes. Survives laptop sleep, network changes, VPN drops.
          </div>
        </div>
      </div>

      <Arrow vertical color={COLORS.green} />

      {/* ROW 5: Notifications */}
      <SectionLabel>Notifications</SectionLabel>
      <div style={{ display: "flex", justifyContent: "center", gap: 16, flexWrap: "wrap" }}>
        <Box icon="📱" title="PUSH NOTIFY" color="purple"
          items={["ntfy.sh (free/self-host)", "Pushover ($5 one-time)", "Job started / ETA", "Complete / error + log tail"]} />
        <Box icon="🖥️" title="DESKTOP NOTIFY" color="blue"
          items={["libnotify (Linux)", "notify-send popup", "System tray icon", "Job status badge"]} />
        <Box icon="📊" title="STATUS TUI" color="green"
          items={["Live squeue table", "Progress bar (time)", "Output file tail", "Resource usage"]} />
      </div>

      <Arrow vertical color={COLORS.green} />

      {/* ROW 6: Data back */}
      <SectionLabel>Results Retrieved</SectionLabel>
      <div style={{ display: "flex", justifyContent: "center" }}>
        <Box icon="📥" title="AUTO-SYNC COMPLETE" color="green" wide
          items={["rsync $SCRATCH/jobname/ → ./results/", "Verify file count + sizes", "Optional: archive on cluster", "Notify: ready to analyse"]} />
      </div>

    </div>
  );
}

function UITab() {
  const [activeJob] = useState(0);
  const jobs = [
    { name: "nanoparticle_sweep_T300", id: "14829341", status: "RUNNING", partition: "gpu", elapsed: "3:42:17", limit: "8:00:00", gpu: "A100×2", node: "ng20301", pct: 46 },
    { name: "dipole_assembly_N512", id: "14829108", status: "PENDING", partition: "gpu", elapsed: "--:--:--", limit: "12:00:00", gpu: "A100×4", node: "—", pct: 0 },
    { name: "mc_equil_run_07", id: "14828874", status: "COMPLETED", partition: "gpu", elapsed: "5:11:03", limit: "6:00:00", gpu: "A100×1", node: "ng20298", pct: 100 },
  ];

  const statusColor = { RUNNING: COLORS.green, PENDING: COLORS.amber, COMPLETED: COLORS.blue, FAILED: COLORS.red };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Titlebar */}
      <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: "8px 16px", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: COLORS.green, boxShadow: `0 0 6px ${COLORS.green}` }} />
          <span style={{ fontFamily: COLORS.mono, fontSize: 13, color: COLORS.textBright, fontWeight: 700, letterSpacing: "0.05em" }}>ClusterPilot</span>
          <Tag color="green">cedar.computecanada.ca</Tag>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <Tag color="amber">3 jobs tracked</Tag>
          <Tag color="blue">SSH active</Tag>
        </div>
      </div>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {/* Left: job list */}
        <div style={{ flex: "1 1 280px", display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 9, letterSpacing: "0.15em" }}>ACTIVE JOBS</div>
          {jobs.map((job, i) => (
            <div key={i} style={{
              background: i === activeJob ? "#131d2e" : COLORS.panel,
              border: `1px solid ${i === activeJob ? COLORS.borderBright : COLORS.border}`,
              borderLeft: `3px solid ${statusColor[job.status]}`,
              borderRadius: 6, padding: "8px 12px", cursor: "pointer",
            }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontFamily: COLORS.mono, fontSize: 10, color: COLORS.textBright, fontWeight: 600 }}>{job.name}</span>
                <Tag color={job.status === "RUNNING" ? "green" : job.status === "PENDING" ? "amber" : "blue"}>{job.status}</Tag>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim }}>#{job.id}</span>
                <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim }}>{job.gpu}</span>
                <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim }}>{job.elapsed} / {job.limit}</span>
              </div>
              {job.status === "RUNNING" && (
                <div style={{ marginTop: 5, height: 3, background: COLORS.border, borderRadius: 2 }}>
                  <div style={{ height: "100%", width: `${job.pct}%`, background: `linear-gradient(to right, ${COLORS.greenDim}, ${COLORS.green})`, borderRadius: 2 }} />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Right: new job panel */}
        <div style={{ flex: "1 1 280px", background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: "12px" }}>
          <div style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 9, letterSpacing: "0.15em", marginBottom: 8 }}>NEW JOB</div>

          <div style={{ marginBottom: 8 }}>
            <div style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 9, marginBottom: 3 }}>DESCRIBE YOUR JOB</div>
            <div style={{
              background: "#0a0e14", border: `1px solid ${COLORS.borderBright}`, borderRadius: 5,
              padding: "8px 10px", fontFamily: COLORS.mono, fontSize: 10, color: COLORS.text, lineHeight: 1.6,
            }}>
              Run SpinGlassLab MC sweep over temperatures 100–400K, N=1024 particles, 10 replicas, CUDA kernel on 2 A100s, ~5 hours
              <span style={{ display: "inline-block", width: 6, height: 10, background: COLORS.green, marginLeft: 2, animation: "blink 1s step-end infinite" }} />
            </div>
          </div>

          <div style={{ marginBottom: 8 }}>
            <div style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 9, marginBottom: 3 }}>AI-GENERATED SLURM SCRIPT</div>
            <div style={{
              background: "#0a0e14", border: `1px solid ${COLORS.greenDim}`, borderRadius: 5,
              padding: "8px 10px", fontFamily: COLORS.mono, fontSize: 9, color: COLORS.text, lineHeight: 1.7,
              maxHeight: 130, overflowY: "auto",
            }}>
              <span style={{ color: COLORS.textDim }}>#!/bin/bash</span>{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--job-name</span>=mc_sweep_T100_400{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--account</span>=def-yoursupervisor{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--gres</span>=gpu:a100:2{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--cpus-per-task</span>=8{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--mem</span>=32G{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--time</span>=06:00:00{"\n"}
              <span style={{ color: COLORS.purple }}>#SBATCH</span> <span style={{ color: COLORS.amber }}>--output</span>=%x-%j.out{"\n"}
              <span style={{ color: COLORS.textDim }}>module load julia/1.10 cuda/12.2</span>{"\n"}
              <span style={{ color: COLORS.green }}>julia --project=. run_sweep.jl</span>
            </div>
          </div>

          <div style={{ display: "flex", gap: 6 }}>
            <div style={{ flex: 1, background: "#0a0e14", border: `1px solid ${COLORS.border}`, borderRadius: 5, padding: "5px 8px" }}>
              <div style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 8 }}>UPLOAD FILES</div>
              <div style={{ color: COLORS.text, fontFamily: COLORS.mono, fontSize: 9, marginTop: 2 }}>run_sweep.jl, Project.toml</div>
            </div>
            <button style={{
              background: `linear-gradient(135deg, ${COLORS.greenDim}, #15803d)`,
              border: `1px solid ${COLORS.green}`, borderRadius: 5,
              color: COLORS.green, fontFamily: COLORS.mono, fontSize: 10, fontWeight: 700,
              padding: "5px 14px", cursor: "pointer", letterSpacing: "0.05em",
            }}>SUBMIT →</button>
          </div>
        </div>
      </div>

      {/* Notification settings strip */}
      <div style={{ background: COLORS.panel, border: `1px solid ${COLORS.border}`, borderRadius: 8, padding: "10px 16px" }}>
        <div style={{ color: COLORS.textDim, fontFamily: COLORS.mono, fontSize: 9, letterSpacing: "0.15em", marginBottom: 6 }}>NOTIFICATIONS</div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          {[
            { label: "Job started", on: true, color: "blue" },
            { label: "ETA update (every 30min)", on: true, color: "blue" },
            { label: "Completed + auto-sync", on: true, color: "green" },
            { label: "Failed + log tail", on: true, color: "red" },
            { label: "Low walltime warning", on: false, color: "amber" },
          ].map((item, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{
                width: 20, height: 10, borderRadius: 5,
                background: item.on ? COLORS.green : COLORS.border,
                position: "relative",
              }}>
                <div style={{
                  width: 8, height: 8, borderRadius: "50%", background: "white",
                  position: "absolute", top: 1, left: item.on ? 11 : 1,
                }} />
              </div>
              <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: item.on ? COLORS.text : COLORS.textDim }}>{item.label}</span>
            </div>
          ))}
          <div style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
            <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim }}>via</span>
            <Tag color="purple">ntfy.sh/julia-hpc</Tag>
          </div>
        </div>
      </div>
    </div>
  );
}

function ArchTab() {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {/* Workstation side */}
        <div style={{
          flex: "1 1 220px", background: COLORS.panel,
          border: `1px solid ${COLORS.blueDim}`, borderTop: `2px solid ${COLORS.blue}`,
          borderRadius: 8, padding: "12px",
        }}>
          <div style={{ color: COLORS.blue, fontFamily: COLORS.mono, fontSize: 11, fontWeight: 700, marginBottom: 8 }}>🖥️ WORKSTATION</div>
          {[
            { name: "clusterpilot UI", desc: "TUI (Textual) or Electron", color: "blue" },
            { name: "ssh-agent", desc: "holds decrypted key in memory", color: "amber" },
            { name: "config.toml", desc: "cluster profiles, account names", color: "amber" },
            { name: "poll.service", desc: "systemd user service, always-on", color: "green" },
            { name: "local DB (SQLite)", desc: "job history, outputs, metadata", color: "purple" },
            { name: "ntfy client", desc: "push to phone on job events", color: "purple" },
          ].map((c, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0", borderBottom: `1px solid ${COLORS.border}` }}>
              <Tag color={c.color}>{c.name}</Tag>
              <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim }}>{c.desc}</span>
            </div>
          ))}
        </div>

        {/* Arrow */}
        <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", gap: 8 }}>
          <div style={{ fontFamily: COLORS.mono, fontSize: 8, color: COLORS.textDim, textAlign: "center" }}>SSH<br/>ControlMaster</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {["rsync ↑", "sbatch", "squeue", "rsync ↓"].map((t, i) => (
              <div key={i} style={{ fontFamily: COLORS.mono, fontSize: 8, color: COLORS.green, background: COLORS.greenDim, borderRadius: 3, padding: "1px 5px" }}>{t}</div>
            ))}
          </div>
        </div>

        {/* Cluster side */}
        <div style={{
          flex: "1 1 220px", background: COLORS.panel,
          border: `1px solid ${COLORS.greenDim}`, borderTop: `2px solid ${COLORS.green}`,
          borderRadius: 8, padding: "12px",
        }}>
          <div style={{ color: COLORS.green, fontFamily: COLORS.mono, fontSize: 11, fontWeight: 700, marginBottom: 8 }}>🏔️ COMPUTE CANADA (cedar/narval)</div>
          {[
            { name: "login node", desc: "ssh entry point, job submission", color: "green" },
            { name: "SLURM ctld", desc: "scheduler, resource manager", color: "green" },
            { name: "$SCRATCH/", desc: "fast parallel FS, job I/O lives here", color: "amber" },
            { name: "compute nodes", desc: "GPU A100s, actual simulation", color: "blue" },
            { name: "module system", desc: "julia, cuda, gcc — probed on setup", color: "blue" },
            { name: "slurm-JOB.out", desc: "stdout/stderr, tailed on error", color: "red" },
          ].map((c, i) => (
            <div key={i} style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0", borderBottom: `1px solid ${COLORS.border}` }}>
              <Tag color={c.color}>{c.name}</Tag>
              <span style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim }}>{c.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* SSH strategy explanation */}
      <div style={{
        background: COLORS.panel, border: `1px solid ${COLORS.amberDim}`,
        borderLeft: `3px solid ${COLORS.amber}`, borderRadius: 8, padding: "12px 16px",
      }}>
        <div style={{ color: COLORS.amber, fontFamily: COLORS.mono, fontSize: 11, fontWeight: 700, marginBottom: 6 }}>
          ⚡ The "No Disconnect" Strategy — SSH ControlMaster
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {[
            { title: "~/.ssh/config", code: `Host cedar\n  HostName cedar.computecanada.ca\n  ControlMaster auto\n  ControlPath ~/.ssh/cm_%h_%p_%r\n  ControlPersist 4h` },
            { title: "What this means", code: "First connect: user types password/2FA\nAll subsequent connects: instant,\nno auth, reuse the socket.\nSurvives: sleep, VPN, WiFi change\n(socket stays until ControlPersist expires)" },
            { title: "Poll daemon loop", code: "every 5 min:\n  ssh cedar 'squeue -j $JOB_ID -h'\n  if COMPLETED → rsync pull\n  if FAILED → fetch log tail\n  else → update local DB\nno user interaction needed" },
          ].map((item, i) => (
            <div key={i} style={{ flex: "1 1 180px", background: "#0a0e14", borderRadius: 5, padding: "8px 10px" }}>
              <div style={{ color: COLORS.amber, fontFamily: COLORS.mono, fontSize: 9, fontWeight: 700, marginBottom: 4 }}>{item.title}</div>
              <pre style={{ color: COLORS.text, fontFamily: COLORS.mono, fontSize: 8.5, margin: 0, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{item.code}</pre>
            </div>
          ))}
        </div>
      </div>

      {/* Notification stack */}
      <div style={{
        background: COLORS.panel, border: `1px solid ${COLORS.purpleDim}`,
        borderLeft: `3px solid ${COLORS.purple}`, borderRadius: 8, padding: "12px 16px",
      }}>
        <div style={{ color: COLORS.purple, fontFamily: COLORS.mono, fontSize: 11, fontWeight: 700, marginBottom: 6 }}>
          📱 Notification Stack Options
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {[
            { name: "ntfy.sh", pros: "Free, open-source, self-hostable, Android + iOS app", tag: "RECOMMENDED", tagColor: "green" },
            { name: "Pushover", pros: "$5 one-time, polished iOS/Android app, reliable delivery", tag: "POLISHED", tagColor: "blue" },
            { name: "Telegram bot", pros: "Free, no app install needed if already using Telegram", tag: "EASY", tagColor: "amber" },
            { name: "Email/SMTP", pros: "Compute Canada already supports this via #SBATCH --mail-type", tag: "FALLBACK", tagColor: "purple" },
          ].map((item, i) => (
            <div key={i} style={{ flex: "1 1 200px", background: "#0a0e14", borderRadius: 5, padding: "8px 10px" }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontFamily: COLORS.mono, fontSize: 10, fontWeight: 700, color: COLORS.textBright }}>{item.name}</span>
                <Tag color={item.tagColor}>{item.tag}</Tag>
              </div>
              <div style={{ fontFamily: COLORS.mono, fontSize: 9, color: COLORS.textDim, lineHeight: 1.5 }}>{item.pros}</div>
            </div>
          ))}
        </div>
      </div>

    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState("flow");
  const tabs = [
    { id: "flow", label: "WORKFLOW" },
    { id: "ui", label: "UI MOCKUP" },
    { id: "arch", label: "ARCHITECTURE" },
  ];

  return (
    <div style={{
      background: COLORS.bg, minHeight: "100vh", padding: "20px 16px",
      fontFamily: COLORS.sans, color: COLORS.text,
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=DM+Sans:wght@400;600&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: ${COLORS.bg}; }
        ::-webkit-scrollbar-thumb { background: ${COLORS.borderBright}; border-radius: 2px; }
        @keyframes blink { 0%,100% { opacity: 1; } 50% { opacity: 0; } }
      `}</style>

      {/* Header */}
      <div style={{ textAlign: "center", marginBottom: 20 }}>
        <div style={{ fontFamily: COLORS.mono, fontSize: 22, fontWeight: 700, color: COLORS.textBright, letterSpacing: "0.1em" }}>
          CLUSTER<span style={{ color: COLORS.green }}>PILOT</span>
        </div>
        <div style={{ fontFamily: COLORS.mono, fontSize: 10, color: COLORS.textDim, letterSpacing: "0.2em", marginTop: 2 }}>
          AI-ASSISTED HPC WORKFLOW MANAGER — COMPUTE CANADA
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16, justifyContent: "center" }}>
        {tabs.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)} style={{
            background: tab === t.id ? COLORS.blueDim : "transparent",
            border: `1px solid ${tab === t.id ? COLORS.blue : COLORS.border}`,
            borderRadius: 6, color: tab === t.id ? COLORS.blue : COLORS.textDim,
            fontFamily: COLORS.mono, fontSize: 10, fontWeight: 700, letterSpacing: "0.1em",
            padding: "5px 16px", cursor: "pointer",
          }}>{t.label}</button>
        ))}
      </div>

      {tab === "flow" && <FlowTab />}
      {tab === "ui" && <UITab />}
      {tab === "arch" && <ArchTab />}
    </div>
  );
}
