import { useMemo, useState } from "react";

import { T, STATUS } from "../theme.js";
import { walltimePct, formatDatetime, firstErrorLine, describeExit } from "../format.js";
import { StatusBadge, ProgressBar } from "../components/primitives.jsx";
import { jobPath } from "../router.js";

const ALL = "all";

// Five columns, not seven. Partition is a submit-time decision nobody scans
// by and Account only matters for the usage report, so both moved to the
// detail page (issue #50). What is left gets room for two lines.
const GRID = "minmax(240px, 2.2fr) minmax(150px, 1.3fr) 110px minmax(170px, 1.5fr) 130px 18px";

const keyOf = (j) => `${j.cluster_name}/${j.slurm_job_id}`;

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

export default function JobsPage({
  jobs, loading, navigate, onLoadOlder, loadingOlder, exhausted,
}) {
  const [query, setQuery] = useState("");
  const [cluster, setCluster] = useState(ALL);
  const [status, setStatus] = useState(ALL);

  const clusters = useMemo(
    () => [...new Set(jobs.map(j => j.cluster_name).filter(Boolean))].sort(), [jobs]);
  const statuses = useMemo(
    () => [...new Set(jobs.map(j => j.status).filter(Boolean))].sort(), [jobs]);

  const visible = useMemo(() => jobs.filter(j =>
    matches(j, query)
    && (cluster === ALL || j.cluster_name === cluster)
    && (status === ALL || j.status === status)
  ), [jobs, query, cluster, status]);

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

      <div style={{ flex: 1, overflow: "auto" }}>
        <div style={{
          display: "grid", gridTemplateColumns: GRID, gap: 14,
          padding: "10px 20px", borderBottom: `1px solid ${T.border}`,
          background: T.panel, position: "sticky", top: 0, zIndex: 1,
        }}>
          {["Job", "Status", "Cluster", "Walltime used / req.", "Submitted", ""].map((h, i) => (
            <div key={i} style={{
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
          const pct = walltimePct(j.walltime_consumed, j.walltime_requested);
          const failed = j.status !== "COMPLETED" && j.status !== "RUNNING" && j.status !== "PENDING";
          // The answer goes in the list; the evidence lives on the job's own
          // page (issue #50). Most of the time this is all you needed.
          const reason = failed ? describeExit(j.exit_code) : null;
          const excerpt = failed ? firstErrorLine(j.log_tail) : null;

          return (
            <div
              key={keyOf(j)}
              onClick={() => navigate(jobPath(j))}
              onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); navigate(jobPath(j)); } }}
              role="link"
              tabIndex={0}
              aria-label={`${j.job_name ?? j.slurm_job_id} on ${j.cluster_name}`}
              style={{
                display: "grid", gridTemplateColumns: GRID, gap: 14,
                padding: "11px 20px", borderBottom: `1px solid ${T.border}`,
                cursor: "pointer", alignItems: "start",
              }}
            >
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: T.mono, fontSize: 15, color: T.text }}>
                  {j.job_name ?? `#${j.slurm_job_id}`}
                </div>
                <div style={{ fontFamily: T.sans, fontSize: 13, color: T.dim, marginTop: 2 }}>
                  #{j.slurm_job_id}{j.array_spec ? ` · array ${j.array_spec}` : ""}
                </div>
                {excerpt && (
                  <div style={{
                    fontFamily: T.mono, fontSize: 12.5, color: T.red, marginTop: 4,
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  }} title={excerpt}>{excerpt}</div>
                )}
              </div>

              <div>
                <StatusBadge status={j.status} />
                {j.status_detail && (
                  <div style={{ fontFamily: T.mono, fontSize: 12, color: T.muted, marginTop: 3 }}>
                    {j.status_detail}
                  </div>
                )}
                {reason && (
                  <div style={{ fontFamily: T.mono, fontSize: 12, color: T.red, marginTop: 3 }}>
                    {reason}
                  </div>
                )}
              </div>

              <div style={{ fontFamily: T.mono, fontSize: 15, color: T.muted }}>{j.cluster_name}</div>

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

              <div style={{ fontFamily: T.mono, fontSize: 16, color: T.dim, textAlign: "right" }}>›</div>
            </div>
          );
        })}

        {/* A button, not infinite scroll: scroll hijacking fights the back
            button, and now that each job has a URL it would make a job's
            position unreproducible. */}
        <div style={{ padding: "16px 20px", textAlign: "center" }}>
          {exhausted ? (
            <span style={{ fontFamily: T.sans, fontSize: 14, color: T.dim }}>
              That is every job ClusterPilot has synced.
            </span>
          ) : (
            <button
              onClick={onLoadOlder}
              disabled={loadingOlder}
              style={{
                background: "transparent", border: `1px solid ${T.border2}`,
                borderRadius: 5, padding: "9px 18px", fontFamily: T.sans,
                fontSize: 15, color: loadingOlder ? T.dim : T.amberText,
                cursor: loadingOlder ? "default" : "pointer",
              }}
            >
              {loadingOlder ? "Loading..." : "Load older jobs"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
