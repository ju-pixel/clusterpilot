import { useState, useEffect } from "react";
import { RedirectToSignIn, useUser, useAuth, useClerk } from "@clerk/react";
import { makeApiClient } from "./api.js";

// ── Design tokens ─────────────────────────────────────────────────────────────
const T = {
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

const STATUS = {
  RUNNING:   { fg: T.green, bg: T.greenDim, icon: "▶" },
  PENDING:   { fg: T.amber, bg: T.amberLo,  icon: "◈" },
  COMPLETED: { fg: T.cyan,  bg: T.cyanDim,  icon: "✓" },
  FAILED:    { fg: T.red,   bg: T.redDim,   icon: "✗" },
  CANCELLED: { fg: T.red,   bg: T.redDim,   icon: "✗" },
  TIMEOUT:   { fg: T.red,   bg: T.redDim,   icon: "⏰" },
};

// ── Cluster metadata (static display info — connections managed by TUI) ───────
const CLUSTER_META = {
  cedar:  { full: "cedar.computecanada.ca",  type: "drac" },
  narval: { full: "narval.computecanada.ca", type: "drac" },
  grex:   { full: "yak.hpc.umanitoba.ca",    type: "grex" },
};

// ── Walltime helpers ──────────────────────────────────────────────────────────
function walltimeToSeconds(s) {
  if (!s) return 0;
  const parts = s.split(":").map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return 0;
}

function walltimePct(consumed, requested) {
  const c = walltimeToSeconds(consumed);
  const r = walltimeToSeconds(requested);
  if (!r || !c) return 0;
  return Math.min(100, Math.round((c / r) * 100));
}

function formatDatetime(iso) {
  if (!iso) return "─";
  return iso.replace("T", " ").slice(0, 16);
}

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
      fontFamily: T.mono, fontSize: 14, fontWeight: 600,
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
      <span style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>{pct}%</span>
    </div>
  );
}

function Dot({ color }) {
  return <span style={{ color, fontSize: 11, lineHeight: 1 }}>●</span>;
}

function SectionLabel({ children }) {
  return (
    <div style={{
      fontFamily: T.sans, fontSize: 13, fontWeight: 600,
      color: T.dim, textTransform: "uppercase", letterSpacing: "0.1em",
      padding: "0 16px", marginBottom: 6,
    }}>{children}</div>
  );
}

// ── SLURM script with basic syntax colouring ──────────────────────────────────
function SlurmScript({ src }) {
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

function JobsPage({ jobs, loading }) {
  const [selectedId, setSelectedId] = useState(null);
  const [detailTab, setDetailTab] = useState("script");

  // Auto-select first job once loaded
  useEffect(() => {
    if (jobs.length > 0 && selectedId === null) {
      setSelectedId(jobs[0].slurm_job_id);
    }
  }, [jobs, selectedId]);

  const job = jobs.find(j => j.slurm_job_id === selectedId) ?? null;
  const sc = job ? (STATUS[job.status] ?? STATUS.PENDING) : null;

  if (loading) {
    return (
      <div style={{ padding: 32, fontFamily: T.mono, fontSize: 15, color: T.dim }}>
        Loading jobs...
      </div>
    );
  }

  if (jobs.length === 0) {
    return (
      <div style={{ padding: 32, fontFamily: T.sans, fontSize: 16, color: T.dim }}>
        No jobs yet. Submit a job from the ClusterPilot TUI and it will appear here.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flex: 1, overflow: "hidden", gap: 0 }}>

      {/* ── JOB TABLE ──────────────────────────────────────────────────── */}
      <div style={{ flex: 1, overflow: "auto", borderRight: `1px solid ${T.border}` }}>

        {/* table header */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "200px 130px 100px 110px 230px 160px",
          padding: "10px 20px",
          borderBottom: `1px solid ${T.border}`,
          background: T.panel,
          position: "sticky", top: 0, zIndex: 1,
        }}>
          {["Job", "Status", "Cluster", "Partition", "Walltime used / req.", "Submitted"].map(h => (
            <div key={h} style={{
              fontFamily: T.sans, fontSize: 14, fontWeight: 600,
              color: T.dim, textTransform: "uppercase", letterSpacing: "0.07em",
            }}>{h}</div>
          ))}
        </div>

        {jobs.map(j => {
          const s = STATUS[j.status] ?? STATUS.PENDING;
          const active = j.slurm_job_id === selectedId;
          const pct = walltimePct(j.walltime_consumed, j.walltime_requested);
          return (
            <div key={j.slurm_job_id} onClick={() => setSelectedId(j.slurm_job_id)} style={{
              display: "grid",
              gridTemplateColumns: "200px 130px 100px 110px 230px 160px",
              padding: "11px 20px",
              borderBottom: `1px solid ${T.border}`,
              background: active ? `${T.amber}08` : "transparent",
              borderLeft: `2px solid ${active ? T.amber : "transparent"}`,
              cursor: "pointer",
              alignItems: "center",
            }}>
              {/* job id + name */}
              <div>
                <div style={{ fontFamily: T.mono, fontSize: 15, color: T.text, fontWeight: active ? 500 : 400 }}>
                  {j.job_name ?? `#${j.slurm_job_id}`}
                </div>
                <div style={{ fontFamily: T.sans, fontSize: 13, color: T.dim, marginTop: 2 }}>
                  #{j.slurm_job_id} · {j.cluster_name}
                </div>
              </div>
              {/* status */}
              <div><StatusBadge status={j.status} /></div>
              {/* cluster */}
              <div style={{ fontFamily: T.mono, fontSize: 15, color: T.muted }}>{j.cluster_name}</div>
              {/* partition */}
              <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim }}>{j.partition ?? "─"}</div>
              {/* walltime */}
              <div>
                <div style={{ fontFamily: T.mono, fontSize: 15, color: s.fg }}>
                  {j.walltime_consumed ?? "─:──:──"} / {j.walltime_requested ?? "─:──:──"}
                </div>
                {j.status !== "PENDING" && (j.walltime_consumed || j.walltime_requested) && (
                  <div style={{ marginTop: 5 }}>
                    <ProgressBar pct={pct} color={s.fg} />
                  </div>
                )}
              </div>
              {/* submitted */}
              <div style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>{formatDatetime(j.submitted_at)}</div>
            </div>
          );
        })}
      </div>

      {/* ── JOB DETAIL ──────────────────────────────────────────────────── */}
      {job && (
        <div style={{
          width: 520, flexShrink: 0,
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
              <div>
                <span style={{ fontFamily: T.mono, fontSize: 16, fontWeight: 600, color: T.text }}>
                  {job.job_name ?? `#${job.slurm_job_id}`}
                </span>
                {job.job_name && (
                  <span style={{ fontFamily: T.mono, fontSize: 13, color: T.dim, marginLeft: 10 }}>
                    #{job.slurm_job_id}
                  </span>
                )}
              </div>
              <StatusBadge status={job.status} />
            </div>
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {[
                ["cluster",   job.cluster_name],
                ["partition", job.partition ?? "─"],
                ["submitted", formatDatetime(job.submitted_at)],
              ].map(([k, v]) => (
                <div key={k}>
                  <span style={{ fontFamily: T.mono, fontSize: 13, color: T.dim }}>{k} </span>
                  <span style={{ fontFamily: T.mono, fontSize: 14, color: T.muted }}>{v}</span>
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
                fontFamily: T.sans, fontSize: 15, fontWeight: 500,
                color: detailTab === tab ? T.amber : T.dim,
                borderBottom: `2px solid ${detailTab === tab ? T.amber : "transparent"}`,
                textTransform: "capitalize",
              }}>{tab}</button>
            ))}
          </div>

          {/* tab content */}
          <div style={{ flex: 1, overflow: "auto", background: T.bg }}>
            {detailTab === "script" && (
              <SlurmScript src={job.script} />
            )}

            {detailTab === "logs" && (
              <div style={{ padding: "12px 16px" }}>
                {job.log_tail
                  ? job.log_tail.split("\n").map((line, i) => (
                      <div key={i} style={{
                        fontFamily: T.mono, fontSize: 15, lineHeight: 1.7,
                        color: line.includes("error") || line.includes("ERROR") ? T.red
                             : line.includes("done") || line.includes("completed") ? T.green
                             : line.includes("running") ? T.amber
                             : T.muted,
                      }}>{line}</div>
                    ))
                  : <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim, padding: "4px 0" }}>
                      No log output available.
                    </div>
                }
              </div>
            )}

            {detailTab === "parameters" && (
              <div style={{ padding: "14px 16px" }}>
                <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim, lineHeight: 1.7 }}>
                  Parameters are not captured in this version.
                  Use Fieldnotes to record simulation parameters alongside this job.
                </div>
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
            <span style={{ fontFamily: T.sans, fontSize: 14, color: T.dim }}>
              Fieldnotes run
            </span>
            {job.fieldnotes_run_id ? (
              <span style={{ fontFamily: T.mono, fontSize: 14, color: "#3D74F6" }}>
                → fn://runs/{job.fieldnotes_run_id} ↗
              </span>
            ) : (
              <span style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>not linked</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function NotificationsPage() {
  const { getToken } = useAuth();
  const api = makeApiClient(getToken);

  const [prefs, setPrefs] = useState(null);
  const [topic, setTopic] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getNotifyPrefs()
      .then(data => {
        setPrefs(data);
        setTopic(data.ntfy_topic ?? "");
      })
      .catch(() => {});
  }, []);

  async function handleToggle(key) {
    if (!prefs) return;
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    try {
      await api.updateNotifyPrefs(updated);
    } catch {
      setPrefs(prefs); // revert on error
    }
  }

  async function handleSaveTopic() {
    if (!prefs) return;
    setSaving(true);
    try {
      const updated = { ...prefs, ntfy_topic: topic || null };
      await api.updateNotifyPrefs(updated);
      setPrefs(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  const TOGGLES = [
    { label: "Job starts running",  sub: "PENDING → RUNNING",              key: "notify_on_start"         },
    { label: "Job completes",       sub: "RUNNING → COMPLETED",            key: "notify_on_complete"      },
    { label: "Job fails",           sub: "RUNNING → FAILED / TIMEOUT",     key: "notify_on_fail"          },
    { label: "Walltime warning",    sub: "less than 30 minutes remaining",  key: "notify_on_walltime_warn" },
  ];

  return (
    <div style={{ padding: "28px 32px", maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 4px", fontFamily: T.sans, fontSize: 22, fontWeight: 600, color: T.text }}>
        Notifications
      </h2>
      <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
        ClusterPilot sends notifications via ntfy.sh or any compatible webhook.
      </p>

      {/* ntfy topic */}
      <div style={{ marginBottom: 24 }}>
        <label style={{ display: "block", fontFamily: T.sans, fontSize: 15, fontWeight: 600, color: T.muted, marginBottom: 6 }}>
          ntfy.sh topic URL
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="https://ntfy.sh/your-topic"
            style={{
              flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
              borderRadius: 5, padding: "8px 12px",
              fontFamily: T.mono, fontSize: 15, color: T.text,
              outline: "none",
            }}
          />
          <button
            onClick={() => { if (topic) navigator.clipboard.writeText(topic); }}
            style={btnStyle}
          >
            Copy
          </button>
          <button onClick={handleSaveTopic} disabled={saving} style={btnStyle}>
            {saved ? "Saved" : saving ? "Saving..." : "Save"}
          </button>
        </div>
        {topic && (
          <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim }}>
            Subscribe on any device:{" "}
            <span style={{ fontFamily: T.mono, color: T.muted }}>
              ntfy subscribe {topic.split("/").pop()}
            </span>
          </p>
        )}
      </div>

      {/* event toggles */}
      <div>
        <div style={{ fontFamily: T.sans, fontSize: 15, fontWeight: 600, color: T.muted, marginBottom: 12 }}>
          Send a notification when
        </div>
        {TOGGLES.map(item => {
          const on = prefs ? prefs[item.key] : false;
          return (
            <div key={item.key} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "12px 16px",
              background: T.panel2, border: `1px solid ${T.border}`,
              borderRadius: 6, marginBottom: 8,
            }}>
              <div>
                <div style={{ fontFamily: T.sans, fontSize: 16, color: T.text }}>{item.label}</div>
                <div style={{ fontFamily: T.mono, fontSize: 14, color: T.dim, marginTop: 2 }}>{item.sub}</div>
              </div>
              <div
                onClick={() => handleToggle(item.key)}
                style={{
                  width: 40, height: 22, borderRadius: 11,
                  background: on ? T.amber : T.border2,
                  position: "relative", cursor: "pointer", flexShrink: 0,
                  transition: "background 0.2s",
                }}
              >
                <div style={{
                  position: "absolute", top: 3,
                  left: on ? 20 : 3,
                  width: 16, height: 16, borderRadius: "50%",
                  background: T.text, transition: "left 0.2s",
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function AccountPage({ email, userInfo }) {
  const { getToken } = useAuth();
  const api = makeApiClient(getToken);

  const [keyInfo, setKeyInfo] = useState(undefined); // undefined = loading, null = no key
  const [rotating, setRotating] = useState(false);
  const [newKey, setNewKey] = useState(null); // shown once after issue/rotate
  const [billingLoading, setBillingLoading] = useState(false);
  const [keyError, setKeyError] = useState(null);
  const [billingError, setBillingError] = useState(null);
  const [invites, setInvites] = useState(null); // null = not loaded yet

  useEffect(() => {
    api.getKeys()
      .then(setKeyInfo)
      .catch(() => {
        // 404 means no key issued yet — that's a valid state
        setKeyInfo(null);
      });
    api.getInvites()
      .then(setInvites)
      .catch(() => setInvites([]));
  }, []);

  async function handleIssueOrRotate() {
    setRotating(true);
    setNewKey(null);
    setKeyError(null);
    try {
      const result = keyInfo === null
        ? await api.issueKey()
        : await api.rotateKey();
      setNewKey(result.key);
      setKeyInfo(result);
    } catch (err) {
      setKeyError(err.message || "Request failed.");
    } finally {
      setRotating(false);
    }
  }

  async function handleBillingPortal() {
    setBillingLoading(true);
    setBillingError(null);
    try {
      const { url } = await api.getBillingPortal();
      window.location.href = url;
    } catch (err) {
      setBillingError(err.message || "Could not open billing portal.");
      setBillingLoading(false);
    }
  }

  const hasKey = keyInfo !== null && keyInfo !== undefined;
  const keyDisplay = newKey ?? (hasKey ? keyInfo.key : keyInfo === undefined ? "Loading..." : "No key issued yet");

  return (
    <div style={{ padding: "28px 32px", maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 4px", fontFamily: T.sans, fontSize: 22, fontWeight: 600, color: T.text }}>
        Account
      </h2>
      <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
        {email}
      </p>

      {/* trial banner */}
      {userInfo?.subscription_status === "trialing" && (
        <div style={{
          background: T.amberLo, border: `1px solid ${T.amber}55`,
          borderRadius: 6, padding: "10px 14px", marginBottom: 24,
          fontFamily: T.sans, fontSize: 15, color: T.amber,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{ fontFamily: T.mono }}>◈</span>
          You are on a 14-day free trial. No charge until the trial ends.
        </div>
      )}

      {/* managed API key */}
      <Section title="Managed API Key">
        <p style={{ margin: "0 0 12px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
          ClusterPilot uses this key for SLURM script generation. You do not need your own Anthropic account.
        </p>
        {newKey && (
          <div style={{
            background: T.amberLo, border: `1px solid ${T.amber}44`,
            borderRadius: 5, padding: "8px 12px", marginBottom: 10,
            fontFamily: T.sans, fontSize: 14, color: T.amber,
          }}>
            Copy this key now — it will not be shown again.
          </div>
        )}
        {keyError && (
          <div style={{
            background: T.redDim, border: `1px solid ${T.red}55`,
            borderRadius: 5, padding: "8px 12px", marginBottom: 10,
            fontFamily: T.mono, fontSize: 13, color: T.red,
          }}>
            {keyError}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{
            flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
            borderRadius: 5, padding: "8px 12px",
            fontFamily: T.mono, fontSize: 15, color: T.dim,
            letterSpacing: "0.05em", wordBreak: "break-all",
          }}>{keyDisplay}</div>
          {newKey && (
            <button onClick={() => navigator.clipboard.writeText(newKey)} style={btnStyle}>
              Copy
            </button>
          )}
          <button onClick={handleIssueOrRotate} disabled={rotating || keyInfo === undefined} style={btnStyle}>
            {rotating ? "..." : hasKey ? "Rotate" : "Issue key"}
          </button>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim }}>
          {hasKey
            ? "Rotating issues a new key and invalidates the current one immediately."
            : "Issue a key to start using the managed API from the ClusterPilot TUI."}
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
            <div style={{ fontFamily: T.sans, fontSize: 17, fontWeight: 600, color: T.text }}>
              Researcher{" "}
              <span style={{ fontFamily: T.mono, fontSize: 15, color: T.amber }}>$3 / month</span>
            </div>
            <div style={{ fontFamily: T.sans, fontSize: 15, color: T.dim, marginTop: 3 }}>
              {userInfo?.subscription_status === "trialing" ? "Free trial active"
                : userInfo?.subscription_status === "active" ? "Active"
                : userInfo?.subscription_status ?? "loading..."}
            </div>
          </div>
          <button onClick={handleBillingPortal} disabled={billingLoading} style={btnStyle}>
            {billingLoading ? "..." : "Manage billing ↗"}
          </button>
        </div>
        {billingError && (
          <div style={{
            background: T.redDim, border: `1px solid ${T.red}55`,
            borderRadius: 5, padding: "8px 12px", marginTop: 8,
            fontFamily: T.mono, fontSize: 13, color: T.red,
          }}>
            {billingError}
          </div>
        )}
      </Section>

      {/* group seats — only shown if this user has issued invite codes */}
      {invites !== null && invites.length > 0 && (
        <Section title="Group Seats">
          <p style={{ margin: "0 0 14px", fontFamily: T.sans, fontSize: 15, color: T.dim }}>
            {invites.filter(c => c.redeemed).length} of {invites.length} seats redeemed.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {invites.map(invite => (
              <div key={invite.code} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                background: T.panel2, border: `1px solid ${T.border2}`,
                borderRadius: 5, padding: "8px 14px",
              }}>
                <span style={{ fontFamily: T.mono, fontSize: 16, letterSpacing: "0.1em", color: T.text }}>
                  {invite.code}
                </span>
                <span style={{
                  fontFamily: T.mono, fontSize: 13,
                  color: invite.redeemed ? T.cyan : T.dim,
                }}>
                  {invite.redeemed ? "redeemed" : "pending"}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* danger zone */}
      <Section title="Danger Zone">
        <div style={{
          background: `${T.red}08`, border: `1px solid ${T.red}33`,
          borderRadius: 6, padding: "14px 16px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.red }}>
              Cancel subscription
            </div>
            <div style={{ fontFamily: T.sans, fontSize: 15, color: T.dim, marginTop: 2 }}>
              Revokes managed API key at period end. Local tool still works.
            </div>
          </div>
          <button
            onClick={handleBillingPortal}
            style={{ ...btnStyle, background: T.redDim, border: `1px solid ${T.red}66`, color: T.red }}
          >
            Cancel
          </button>
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
        fontFamily: T.sans, fontSize: 15, fontWeight: 600,
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
  fontFamily: T.sans, fontSize: 15, fontWeight: 500, color: T.muted,
  whiteSpace: "nowrap",
};

// ── Main Dashboard ────────────────────────────────────────────────────────────
const NAV = [
  { id: "jobs",          icon: "▤", label: "Jobs"          },
  { id: "notifications", icon: "◎", label: "Notifications" },
  { id: "account",       icon: "◈", label: "Account"       },
];

function SubscribeGate({ email, getToken }) {
  const api = makeApiClient(getToken);
  const [loading, setLoading] = useState(false);
  const [piLoading, setPiLoading] = useState(false);
  const [piQty, setPiQty] = useState(3);
  const [redeemMode, setRedeemMode] = useState(false);
  const [redeemCode, setRedeemCode] = useState("");
  const [redeemLoading, setRedeemLoading] = useState(false);
  const [redeemError, setRedeemError] = useState(null);

  async function handleSubscribe() {
    setLoading(true);
    try {
      const { url } = await api.createCheckout();
      window.location.href = url;
    } catch {
      setLoading(false);
    }
  }

  async function handlePiCheckout() {
    setPiLoading(true);
    try {
      const { url } = await api.createPiCheckout(piQty);
      window.location.href = url;
    } catch {
      setPiLoading(false);
    }
  }

  async function handleRedeem() {
    setRedeemLoading(true);
    setRedeemError(null);
    try {
      await api.redeemInvite(redeemCode.trim());
      window.location.reload();
    } catch (err) {
      setRedeemError(err.message || "Invalid or already-used code.");
      setRedeemLoading(false);
    }
  }

  return (
    <div style={{
      background: T.bg, minHeight: "100vh", display: "flex",
      flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: T.sans, padding: "0 24px",
    }}>
      <Glow color={T.amber} style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 700, letterSpacing: "0.18em", marginBottom: 40 }}>
        ◈ CLUSTERPILOT
      </Glow>

      {redeemMode ? (
        <div style={{
          background: T.panel, border: `1px solid ${T.border2}`,
          borderRadius: 10, padding: "36px 40px", maxWidth: 460, width: "100%",
        }}>
          <h2 style={{ margin: "0 0 8px", fontFamily: T.sans, fontSize: 22, fontWeight: 700, color: T.text }}>
            Redeem invite code
          </h2>
          <p style={{ margin: "0 0 20px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
            Enter the code your PI shared with you.
          </p>
          <input
            value={redeemCode}
            onChange={e => setRedeemCode(e.target.value.toUpperCase())}
            placeholder="e.g. A3F2B891"
            style={{
              width: "100%", boxSizing: "border-box",
              background: T.panel2, border: `1px solid ${T.border2}`,
              borderRadius: 5, padding: "10px 12px", marginBottom: 12,
              fontFamily: T.mono, fontSize: 18, color: T.text,
              letterSpacing: "0.1em", textAlign: "center",
            }}
          />
          {redeemError && (
            <div style={{
              background: T.redDim, border: `1px solid ${T.red}55`,
              borderRadius: 5, padding: "8px 12px", marginBottom: 12,
              fontFamily: T.mono, fontSize: 13, color: T.red,
            }}>{redeemError}</div>
          )}
          <button
            onClick={handleRedeem}
            disabled={redeemLoading || !redeemCode.trim()}
            style={{
              width: "100%", padding: "12px 0",
              background: T.amber, border: "none", borderRadius: 6,
              fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.bg,
              cursor: (redeemLoading || !redeemCode.trim()) ? "not-allowed" : "pointer",
              opacity: (redeemLoading || !redeemCode.trim()) ? 0.7 : 1,
            }}
          >
            {redeemLoading ? "Checking..." : "Redeem →"}
          </button>
          <button
            onClick={() => setRedeemMode(false)}
            style={{ ...btnStyle, width: "100%", marginTop: 10, textAlign: "center" }}
          >
            Back
          </button>
        </div>
      ) : (
        <>
          <div style={{
            background: T.panel, border: `1px solid ${T.border2}`,
            borderRadius: 10, padding: "36px 40px", maxWidth: 460, width: "100%",
            marginBottom: 16,
          }}>
            <h2 style={{ margin: "0 0 8px", fontFamily: T.sans, fontSize: 22, fontWeight: 700, color: T.text }}>
              Start your free trial
            </h2>
            <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
              14 days free, then $3 / month. Cancel any time.
            </p>
            <div style={{ marginBottom: 28 }}>
              {[
                "Managed API key — no Anthropic account needed",
                "Web dashboard for all job history",
                "Multi-machine sync — one view across all clusters",
                "Priority support",
              ].map(f => (
                <div key={f} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <span style={{ color: T.amber, fontFamily: T.mono, fontSize: 14 }}>✓</span>
                  <span style={{ fontFamily: T.sans, fontSize: 15, color: T.muted }}>{f}</span>
                </div>
              ))}
            </div>
            <button
              onClick={handleSubscribe}
              disabled={loading}
              style={{
                width: "100%", padding: "12px 0",
                background: T.amber, border: "none", borderRadius: 6,
                fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.bg,
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.7 : 1,
              }}
            >
              {loading ? "Redirecting..." : "Start free trial →"}
            </button>
            <p style={{ margin: "14px 0 0", fontFamily: T.mono, fontSize: 13, color: T.dim, textAlign: "center" }}>
              {email}
            </p>
          </div>

          <div style={{
            background: T.panel, border: `1px solid ${T.border2}`,
            borderRadius: 10, padding: "28px 40px", maxWidth: 460, width: "100%",
          }}>
            <h3 style={{ margin: "0 0 6px", fontFamily: T.sans, fontSize: 17, fontWeight: 600, color: T.text }}>
              Buying for your group?
            </h3>
            <p style={{ margin: "0 0 18px", fontFamily: T.sans, fontSize: 15, color: T.dim }}>
              15% off for 3 or more seats. You get one invite code per seat to share with your researchers.
            </p>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
              <label style={{ fontFamily: T.sans, fontSize: 15, color: T.muted, whiteSpace: "nowrap" }}>
                Seats:
              </label>
              <input
                type="number"
                min={3}
                value={piQty}
                onChange={e => setPiQty(Math.max(3, parseInt(e.target.value) || 3))}
                style={{
                  width: 70, background: T.panel2, border: `1px solid ${T.border2}`,
                  borderRadius: 5, padding: "7px 10px",
                  fontFamily: T.mono, fontSize: 15, color: T.text, textAlign: "center",
                }}
              />
              <span style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>
                × $2.55 / month
              </span>
            </div>
            <button
              onClick={handlePiCheckout}
              disabled={piLoading}
              style={{
                width: "100%", padding: "11px 0",
                background: "transparent", border: `1.5px solid ${T.amber}`,
                borderRadius: 6, fontFamily: T.sans, fontSize: 16, fontWeight: 600,
                color: T.amber, cursor: piLoading ? "not-allowed" : "pointer",
                opacity: piLoading ? 0.7 : 1,
              }}
            >
              {piLoading ? "Redirecting..." : "Buy group seats →"}
            </button>
            <p style={{ margin: "12px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim, textAlign: "center" }}>
              Have a code from your PI?{" "}
              <span
                onClick={() => setRedeemMode(true)}
                style={{ color: T.amber, cursor: "pointer", textDecoration: "underline" }}
              >
                Redeem it here
              </span>
            </p>
          </div>
        </>
      )}
    </div>
  );
}

export default function ClusterPilotDashboard() {
  const [activeNav, setActiveNav] = useState("jobs");
  const [jobs, setJobs] = useState([]);
  const [jobsLoading, setJobsLoading] = useState(true);
  const [userInfo, setUserInfo] = useState(null);

  const { isSignedIn, isLoaded, getToken } = useAuth();
  const { user } = useUser();
  const { signOut } = useClerk();
  const email = user?.primaryEmailAddress?.emailAddress ?? "";

  useEffect(() => {
    if (!isSignedIn) return;
    const api = makeApiClient(getToken);
    api.getJobs()
      .then(data => { setJobs(data); setJobsLoading(false); })
      .catch(() => setJobsLoading(false));
    api.getMe().then(setUserInfo).catch(() => {});
  }, [isSignedIn, getToken]);

  if (!isLoaded) return null;
  if (!isSignedIn) return <RedirectToSignIn />;

  // Show subscribe gate for free users once userInfo has loaded
  const subStatus = userInfo?.subscription_status;
  if (userInfo && subStatus !== "active" && subStatus !== "trialing") {
    return <SubscribeGate email={email} getToken={getToken} />;
  }

  const running = jobs.filter(j => j.status === "RUNNING").length;
  const pending = jobs.filter(j => j.status === "PENDING").length;

  // Derive per-cluster counts from live jobs
  const clusterCounts = {};
  jobs.forEach(j => {
    if (!clusterCounts[j.cluster_name]) clusterCounts[j.cluster_name] = { running: 0, pending: 0 };
    if (j.status === "RUNNING")  clusterCounts[j.cluster_name].running++;
    if (j.status === "PENDING")  clusterCounts[j.cluster_name].pending++;
  });

  // Build sidebar cluster list from seen clusters, falling back to CLUSTER_META for display info
  const seenClusters = Object.keys(clusterCounts);
  const sidebarClusters = seenClusters.length > 0
    ? seenClusters.map(name => ({
        short: name,
        type: CLUSTER_META[name]?.type ?? null,
        running: clusterCounts[name].running,
        pending: clusterCounts[name].pending,
      }))
    : Object.entries(CLUSTER_META).map(([name, meta]) => ({
        short: name,
        type: meta.type,
        running: 0,
        pending: 0,
      }));

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
        <Glow color={T.amber} style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 700, letterSpacing: "0.18em" }}>
          ◈ CLUSTERPILOT
        </Glow>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            background: T.panel2, border: `1px solid ${T.border2}`,
            borderRadius: 5, padding: "5px 12px",
            display: "flex", alignItems: "center", gap: 10,
          }}>
            <Glow color={T.amberDim} style={{ fontFamily: T.mono, fontSize: 14 }}>◈</Glow>
            <span style={{ fontFamily: T.mono, fontSize: 15, color: T.dim }}>{email}</span>
          </div>
          <button
            onClick={() => signOut({ redirectUrl: "https://clusterpilot.sh" })}
            style={{
              background: "none", border: `1px solid ${T.border3}`,
              borderRadius: 5, padding: "5px 12px",
              fontFamily: T.mono, fontSize: 13, color: T.dim,
              cursor: "pointer",
            }}
          >
            Sign out
          </button>
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
                fontFamily: T.sans, fontSize: 16, fontWeight: active ? 600 : 400,
              }}>
                <span style={{
                  fontFamily: T.mono, fontSize: 15, width: 14, textAlign: "center",
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
            {sidebarClusters.map(c => (
              <div key={c.short} style={{
                display: "flex", alignItems: "center",
                padding: "6px 16px", gap: 8,
              }}>
                <Dot color={T.green} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: T.mono, fontSize: 15, color: T.muted }}>{c.short}</div>
                  <div style={{ fontFamily: T.mono, fontSize: 13, color: T.dim }}>
                    {c.running > 0
                      ? <><Glow color={T.green} style={{ fontSize: 13 }}>{c.running}</Glow> running</>
                      : c.pending > 0
                      ? <><Glow color={T.amber} style={{ fontSize: 13 }}>{c.pending}</Glow> pending</>
                      : "idle"}
                  </div>
                </div>
                {c.type && (
                  <span style={{ fontFamily: T.mono, fontSize: 12, color: T.border3, textTransform: "uppercase" }}>
                    {c.type}
                  </span>
                )}
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
                <Glow color={T.green} style={{ fontFamily: T.mono, fontSize: 20, fontWeight: 700, display: "block" }}>
                  {running}
                </Glow>
                <div style={{ fontFamily: T.sans, fontSize: 13, color: T.dim, marginTop: 1 }}>running</div>
              </div>
              <div style={{ width: 1, background: T.border }} />
              <div style={{ textAlign: "center" }}>
                <Glow color={T.amber} style={{ fontFamily: T.mono, fontSize: 20, fontWeight: 700, display: "block" }}>
                  {pending}
                </Glow>
                <div style={{ fontFamily: T.sans, fontSize: 13, color: T.dim, marginTop: 1 }}>pending</div>
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
            <h1 style={{ margin: 0, fontFamily: T.sans, fontSize: 20, fontWeight: 600, color: T.text }}>
              {NAV.find(n => n.id === activeNav)?.label}
            </h1>
          </div>

          {/* page content */}
          <div style={{ flex: 1, overflow: "auto", display: "flex" }}>
            {activeNav === "jobs"          && <JobsPage jobs={jobs} loading={jobsLoading} />}
            {activeNav === "notifications" && <NotificationsPage />}
            {activeNav === "account"       && <AccountPage email={email} userInfo={userInfo} />}
          </div>
        </div>
      </div>
    </div>
  );
}
