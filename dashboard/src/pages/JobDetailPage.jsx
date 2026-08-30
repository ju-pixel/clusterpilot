import { useState } from "react";

import { T } from "../theme.js";
import { formatDatetime, formatHours, describeExit } from "../format.js";
import { StatusBadge, SlurmScript } from "../components/primitives.jsx";

// One resource figure. Renders nothing when the number is absent, so a
// cluster that reports no GPUs shows no GPU figure rather than a zero that
// reads as "used none".
function Figure({ label, value, unit }) {
  if (value == null) return null;
  return (
    <div>
      <div style={{ fontFamily: T.sans, fontSize: 12, color: T.dim,
                    textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
      <div style={{ fontFamily: T.mono, fontSize: 19, color: T.text, marginTop: 3 }}>
        {value}{unit ? <span style={{ color: T.muted, fontSize: 14 }}> {unit}</span> : null}
      </div>
    </div>
  );
}

// The provenance line is not decoration: 'measured' figures are ClusterPilot's
// own integration of running tasks over its poll cycles, used where sacct
// cannot reach slurmdbd, and must never be read as a scheduler accounting
// record (issues #47, #50).
function Resources({ job }) {
  const measured = job.accounting_source === "measured";
  const known = job.accounting_source === "sacct" || measured;

  if (!known) {
    return (
      <div style={{ fontFamily: T.sans, fontSize: 15, color: T.dim, lineHeight: 1.65, maxWidth: "60ch" }}>
        No resource accounting for this job yet. ClusterPilot records it when a
        job finishes, so jobs that ran before you upgraded have none, and a
        cluster whose accounting database cannot be reached may have none at all.
      </div>
    );
  }

  return (
    <div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
        gap: 22, maxWidth: 760,
      }}>
        <Figure label="CPUs" value={job.alloc_cpus} unit="per task" />
        <Figure label="GPUs" value={job.alloc_gpus} unit="per task" />
        <Figure label="Nodes" value={job.alloc_nodes} unit="per task" />
        <Figure label="Core-hours" value={formatHours(job.core_seconds)} />
        <Figure label="GPU-hours" value={formatHours(job.gpu_seconds)} />
        <Figure label="Billing-hours" value={formatHours(job.billing_seconds)} />
      </div>
      <div style={{
        marginTop: 20, paddingTop: 14, borderTop: `1px solid ${T.border}`,
        fontFamily: T.sans, fontSize: 14, color: measured ? T.amberText : T.dim,
        lineHeight: 1.6, maxWidth: "68ch",
      }}>
        {measured
          ? "Measured by ClusterPilot from the scheduler's live allocation and its "
            + "own polling, because this cluster's accounting database could not be "
            + "reached. Close, but not a scheduler accounting record."
          : "From your scheduler's own accounting records."}
      </div>
    </div>
  );
}

export default function JobDetailPage({ job, loading, navigate }) {
  const [tab, setTab] = useState("script");

  if (loading) {
    return <div style={{ padding: 32, fontFamily: T.mono, fontSize: 15, color: T.dim }}>Loading...</div>;
  }

  if (!job) {
    return (
      <div style={{ padding: 32, maxWidth: "60ch" }}>
        <p style={{ fontFamily: T.sans, fontSize: 16, color: T.text, margin: "0 0 10px" }}>
          That job is not in your history.
        </p>
        <p style={{ fontFamily: T.sans, fontSize: 15, color: T.dim, margin: "0 0 18px" }}>
          It may belong to a different account, or be older than the jobs synced
          so far.
        </p>
        <button onClick={() => navigate("/jobs")} style={{
          background: "transparent", border: `1px solid ${T.amber}`, borderRadius: 5,
          padding: "8px 14px", fontFamily: T.sans, fontSize: 15, color: T.amberText, cursor: "pointer",
        }}>Back to all jobs</button>
      </div>
    );
  }

  const reason = describeExit(job.exit_code);
  const showReason = reason && job.status !== "COMPLETED";

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      <div style={{ padding: "16px 24px 0", borderBottom: `1px solid ${T.border}`, background: T.panel }}>
        <button onClick={() => navigate("/jobs")} style={{
          background: "transparent", border: "none", padding: 0, cursor: "pointer",
          fontFamily: T.sans, fontSize: 14, color: T.dim, marginBottom: 12,
        }}>&larr; All jobs</button>

        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap", marginBottom: 10 }}>
          <span style={{ fontFamily: T.mono, fontSize: 22, fontWeight: 600, color: T.text }}>
            {job.job_name ?? `#${job.slurm_job_id}`}
          </span>
          <span style={{ fontFamily: T.mono, fontSize: 15, color: T.dim }}>#{job.slurm_job_id}</span>
          <StatusBadge status={job.status} />
          {job.status_detail && (
            <span style={{ fontFamily: T.mono, fontSize: 14, color: T.muted }}>{job.status_detail}</span>
          )}
        </div>

        {showReason && (
          <div style={{ fontFamily: T.mono, fontSize: 15, color: T.red, marginBottom: 10 }}>{reason}</div>
        )}

        <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginBottom: 14 }}>
          {[
            ["cluster", job.cluster_name],
            ["partition", job.partition || "─"],
            ["account", job.account || "─"],
            ["array", job.array_spec || "─"],
            ["walltime", `${job.walltime_consumed ?? "─"} / ${job.walltime_requested ?? "─"}`],
            ["submitted", formatDatetime(job.submitted_at)],
            ["efficiency", job.efficiency || "─"],
          ].map(([k, v]) => (
            <div key={k}>
              <div style={{ fontFamily: T.sans, fontSize: 12, color: T.dim,
                            textTransform: "uppercase", letterSpacing: "0.06em" }}>{k}</div>
              <div style={{ fontFamily: T.mono, fontSize: 14.5, color: T.muted, marginTop: 2 }}>{v}</div>
            </div>
          ))}
        </div>

        <div style={{ display: "flex", gap: 0 }}>
          {["script", "logs", "resources"].map(t => (
            <button key={t} onClick={() => setTab(t)} style={{
              padding: "9px 16px", background: "transparent", border: "none", cursor: "pointer",
              fontFamily: T.sans, fontSize: 15, fontWeight: 500,
              color: tab === t ? T.amberText : T.dim,
              borderBottom: `2px solid ${tab === t ? T.amber : "transparent"}`,
              textTransform: "capitalize",
            }}>{t}</button>
          ))}
        </div>
      </div>

      <div style={{ flex: 1, overflow: "auto", background: T.bg, padding: tab === "script" ? 0 : "20px 24px" }}>
        {tab === "script" && <SlurmScript src={job.script} />}

        {tab === "logs" && (
          job.log_tail
            ? job.log_tail.split("\n").map((line, i) => (
                <div key={i} style={{
                  fontFamily: T.mono, fontSize: 14.5, lineHeight: 1.75,
                  color: /error|fatal|traceback/i.test(line) ? T.red
                       : /done|completed|success/i.test(line) ? T.green
                       : /running|starting/i.test(line) ? T.amberText
                       : T.muted,
                  whiteSpace: "pre-wrap", wordBreak: "break-word",
                }}>{line}</div>
              ))
            : <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim }}>No log output available.</div>
        )}

        {tab === "resources" && <Resources job={job} />}
      </div>

      {job.fieldnotes_run_id && (
        <div style={{
          padding: "10px 24px", borderTop: `1px solid ${T.border}`, background: T.panel,
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <span style={{ fontFamily: T.sans, fontSize: 14, color: T.dim }}>Fieldnotes run</span>
          <span style={{ fontFamily: T.mono, fontSize: 14, color: "#3D74F6" }}>
            → fn://runs/{job.fieldnotes_run_id} ↗
          </span>
        </div>
      )}
    </div>
  );
}
