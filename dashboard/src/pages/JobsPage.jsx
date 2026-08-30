import { useMemo, useState } from "react";

import { T, STATUS } from "../theme.js";
import { walltimePct, formatDatetime, formatHours, describeExit } from "../format.js";
import { StatusBadge, ProgressBar, SlurmScript } from "../components/primitives.jsx";

const ALL = "all";

// Rows are keyed on this everywhere, because slurm_job_id alone is not unique
// once two clusters are in the list.
const keyOf = (j) => `${j.cluster_name}/${j.slurm_job_id}`;

const GRID = "minmax(180px, 1.4fr) 130px 110px 110px 210px 150px";

function matches(job, query) {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    (job.job_name ?? "").toLowerCase().includes(q) ||
    String(job.slurm_job_id).includes(q) ||
    (job.cluster_name ?? "").toLowerCase().includes(q) ||
    (job.account ?? "").toLowerCase().includes(q)
  );
}

const inputStyle = {
  background: T.panel2, border: `1px solid ${T.border2}`, borderRadius: 5,
  padding: "7px 10px", fontFamily: T.sans, fontSize: 14, color: T.text,
};

function Filters({ query, setQuery, cluster, setCluster, status, setStatus,
                   clusters, statuses, shown, total }) {
  return (
    <div style={{
      display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap",
      padding: "10px 20px", borderBottom: `1px solid ${T.border}`, background: T.panel,
    }}>
      <input
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Search name, job id, cluster or account"
        aria-label="Search jobs"
        style={{ ...inputStyle, flex: 1, minWidth: 220 }}
      />
      <select value={cluster} onChange={e => setCluster(e.target.value)}
              aria-label="Filter by cluster" style={inputStyle}>
        <option value={ALL}>All clusters</option>
        {clusters.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
      <select value={status} onChange={e => setStatus(e.target.value)}
              aria-label="Filter by status" style={inputStyle}>
        <option value={ALL}>All statuses</option>
        {statuses.map(s => <option key={s} value={s}>{s}</option>)}
      </select>
      <span style={{ fontFamily: T.sans, fontSize: 13, color: T.dim, whiteSpace: "nowrap" }}>
        {shown === total ? `${total} jobs` : `${shown} of ${total}`}
      </span>
    </div>
  );
}

// One resource figure with its unit. Renders nothing when the number is
// absent, so a cluster that reports no GPUs shows no GPU row rather than a
// zero that reads as "used none".
function Figure({ label, value, unit }) {
  if (value == null) return null;
  return (
    <div>
      <div style={{ fontFamily: T.sans, fontSize: 12, color: T.dim,
                    textTransform: "uppercase", letterSpacing: "0.06em" }}>{label}</div>
      <div style={{ fontFamily: T.mono, fontSize: 15, color: T.text, marginTop: 2 }}>
        {value}{unit ? <span style={{ color: T.muted, fontSize: 13 }}> {unit}</span> : null}
      </div>
    </div>
  );
}

// What the job reserved, and where the numbers came from. The provenance line
// is not decoration: 'measured' figures are ClusterPilot's own integration of
// running tasks over its poll cycles, used where sacct cannot reach slurmdbd,
// and must never be read as a scheduler accounting record.
function Resources({ job }) {
  const measured = job.accounting_source === "measured";
  const known = job.accounting_source === "sacct" || measured;

  if (!known) {
    return (
      <div style={{ padding: "14px 16px", fontFamily: T.sans, fontSize: 14,
                    color: T.dim, lineHeight: 1.6 }}>
        No resource accounting for this job yet. ClusterPilot records it when a
        job finishes, so jobs that ran before you upgraded have none, and a
        cluster whose accounting database cannot be reached may have none at all.
      </div>
    );
  }

  return (
    <div style={{ padding: "14px 16px" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>
        <Figure label="CPUs" value={job.alloc_cpus} unit="per task" />
        <Figure label="GPUs" value={job.alloc_gpus} unit="per task" />
        <Figure label="Nodes" value={job.alloc_nodes} unit="per task" />
        <Figure label="Core-hours" value={formatHours(job.core_seconds)} />
        <Figure label="GPU-hours" value={formatHours(job.gpu_seconds)} />
        <Figure label="Billing-hours" value={formatHours(job.billing_seconds)} />
      </div>
      <div style={{
        marginTop: 14, paddingTop: 10, borderTop: `1px solid ${T.border}`,
        fontFamily: T.sans, fontSize: 13, color: measured ? T.amber : T.dim,
        lineHeight: 1.6,
      }}>
        {measured
          ? "Measured by ClusterPilot from the scheduler's live allocation and "
            + "its own polling, because this cluster's accounting database "
            + "could not be reached. Close, but not a scheduler accounting record."
          : "From your scheduler's own accounting records."}
      </div>
    </div>
  );
}

export default function JobsPage({ jobs, loading }) {
  const [query, setQuery] = useState("");
  const [cluster, setCluster] = useState(ALL);
  const [status, setStatus] = useState(ALL);
  const [selectedKey, setSelectedKey] = useState(null);
  const [detailTab, setDetailTab] = useState("script");

  const clusters = useMemo(
    () => [...new Set(jobs.map(j => j.cluster_name).filter(Boolean))].sort(),
    [jobs],
  );
  const statuses = useMemo(
    () => [...new Set(jobs.map(j => j.status).filter(Boolean))].sort(),
    [jobs],
  );

  const visible = useMemo(() => jobs.filter(j =>
    matches(j, query)
    && (cluster === ALL || j.cluster_name === cluster)
    && (status === ALL || j.status === status)
  ), [jobs, query, cluster, status]);

  // Derived rather than held in an effect: picking the first row when nothing
  // is selected is a render-time decision, and doing it with setState in an
  // effect costs a second render every time the list changes.
  const job = visible.find(j => keyOf(j) === selectedKey) ?? visible[0] ?? null;

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
    <div style={{ display: "flex", flexDirection: "column", flex: 1, overflow: "hidden" }}>
      <Filters
        query={query} setQuery={setQuery}
        cluster={cluster} setCluster={setCluster}
        status={status} setStatus={setStatus}
        clusters={clusters} statuses={statuses}
        shown={visible.length} total={jobs.length}
      />

      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
        {/* ── JOB TABLE ────────────────────────────────────────────────── */}
        <div style={{ flex: 1, overflow: "auto", borderRight: `1px solid ${T.border}` }}>
          <div style={{
            display: "grid", gridTemplateColumns: GRID,
            padding: "10px 20px", borderBottom: `1px solid ${T.border}`,
            background: T.panel, position: "sticky", top: 0, zIndex: 1,
          }}>
            {["Job", "Status", "Cluster", "Partition", "Walltime used / req.", "Submitted"].map(h => (
              <div key={h} style={{
                fontFamily: T.sans, fontSize: 14, fontWeight: 600,
                color: T.dim, textTransform: "uppercase", letterSpacing: "0.07em",
              }}>{h}</div>
            ))}
          </div>

          {visible.length === 0 && (
            <div style={{ padding: 28, fontFamily: T.sans, fontSize: 15, color: T.dim }}>
              No jobs match those filters.
            </div>
          )}

          {visible.map(j => {
            const s = STATUS[j.status] ?? STATUS.PENDING;
            const active = job && keyOf(j) === keyOf(job);
            const pct = walltimePct(j.walltime_consumed, j.walltime_requested);
            return (
              <div key={keyOf(j)} onClick={() => setSelectedKey(keyOf(j))} style={{
                display: "grid", gridTemplateColumns: GRID,
                padding: "11px 20px", borderBottom: `1px solid ${T.border}`,
                background: active ? `${T.amber}08` : "transparent",
                borderLeft: `2px solid ${active ? T.amber : "transparent"}`,
                cursor: "pointer", alignItems: "center",
              }}>
                <div>
                  <div style={{ fontFamily: T.mono, fontSize: 15, color: T.text,
                                fontWeight: active ? 500 : 400 }}>
                    {j.job_name ?? `#${j.slurm_job_id}`}
                  </div>
                  <div style={{ fontFamily: T.sans, fontSize: 13, color: T.dim, marginTop: 2 }}>
                    #{j.slurm_job_id}{j.array_spec ? ` · array ${j.array_spec}` : ""}
                  </div>
                </div>
                <div>
                  <StatusBadge status={j.status} />
                  {j.status_detail && (
                    <div style={{ fontFamily: T.mono, fontSize: 12, color: T.muted, marginTop: 3 }}>
                      {j.status_detail}
                    </div>
                  )}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: 15, color: T.muted }}>{j.cluster_name}</div>
                <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim }}>{j.partition ?? "─"}</div>
                <div>
                  <div style={{ fontFamily: T.mono, fontSize: 15, color: s.fg }}>
                    {j.walltime_consumed ?? "─:──:──"} / {j.walltime_requested ?? "─:──:──"}
                  </div>
                  {j.status !== "PENDING" && (j.walltime_consumed || j.walltime_requested) && (
                    <div style={{ marginTop: 5 }}><ProgressBar pct={pct} color={s.fg} /></div>
                  )}
                </div>
                <div style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>
                  {formatDatetime(j.submitted_at)}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── JOB DETAIL ───────────────────────────────────────────────── */}
        {job && (
          <div style={{ width: 520, flexShrink: 0, display: "flex",
                        flexDirection: "column", overflow: "hidden" }}>
            <div style={{ padding: "14px 18px", borderBottom: `1px solid ${T.border}`,
                          background: T.panel }}>
              <div style={{ display: "flex", alignItems: "center",
                            justifyContent: "space-between", marginBottom: 6 }}>
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
                  ["cluster", job.cluster_name],
                  ["partition", job.partition ?? "─"],
                  ["account", job.account ?? "─"],
                  ["submitted", formatDatetime(job.submitted_at)],
                ].map(([k, v]) => (
                  <div key={k}>
                    <span style={{ fontFamily: T.mono, fontSize: 13, color: T.dim }}>{k} </span>
                    <span style={{ fontFamily: T.mono, fontSize: 14, color: T.muted }}>{v}</span>
                  </div>
                ))}
              </div>
              {describeExit(job.exit_code) && job.status !== "COMPLETED" && (
                <div style={{ marginTop: 8, fontFamily: T.mono, fontSize: 14, color: T.red }}>
                  {describeExit(job.exit_code)}
                </div>
              )}
              {job.efficiency && (
                <div style={{ marginTop: 8, fontFamily: T.mono, fontSize: 14, color: T.muted }}>
                  {job.efficiency}
                </div>
              )}
            </div>

            <div style={{ display: "flex", borderBottom: `1px solid ${T.border}`, background: T.panel }}>
              {["script", "logs", "resources"].map(tab => (
                <button key={tab} onClick={() => setDetailTab(tab)} style={{
                  padding: "8px 16px", background: "transparent", border: "none", cursor: "pointer",
                  fontFamily: T.sans, fontSize: 15, fontWeight: 500,
                  color: detailTab === tab ? T.amber : T.dim,
                  borderBottom: `2px solid ${detailTab === tab ? T.amber : "transparent"}`,
                  textTransform: "capitalize",
                }}>{tab}</button>
              ))}
            </div>

            <div style={{ flex: 1, overflow: "auto", background: T.bg }}>
              {detailTab === "script" && <SlurmScript src={job.script} />}

              {detailTab === "logs" && (
                <div style={{ padding: "12px 16px" }}>
                  {job.log_tail
                    ? job.log_tail.split("\n").map((line, i) => (
                        <div key={i} style={{
                          fontFamily: T.mono, fontSize: 15, lineHeight: 1.7,
                          color: /error/i.test(line) ? T.red
                               : /done|completed/i.test(line) ? T.green
                               : /running/i.test(line) ? T.amber
                               : T.muted,
                        }}>{line}</div>
                      ))
                    : <div style={{ fontFamily: T.mono, fontSize: 15, color: T.dim, padding: "4px 0" }}>
                        No log output available.
                      </div>}
                </div>
              )}

              {detailTab === "resources" && <Resources job={job} />}
            </div>

            {/* Only shown once a run is actually linked. A row that can only
                ever say "not linked" is noise on every job. */}
            {job.fieldnotes_run_id && (
              <div style={{
                padding: "10px 16px", borderTop: `1px solid ${T.border}`, background: T.panel,
                display: "flex", alignItems: "center", justifyContent: "space-between",
              }}>
                <span style={{ fontFamily: T.sans, fontSize: 14, color: T.dim }}>Fieldnotes run</span>
                <span style={{ fontFamily: T.mono, fontSize: 14, color: "#3D74F6" }}>
                  → fn://runs/{job.fieldnotes_run_id} ↗
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
