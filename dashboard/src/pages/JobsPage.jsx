import { useState, useEffect } from "react";

import { T, STATUS } from "../theme.js";
import { walltimePct, formatDatetime } from "../format.js";
import { StatusBadge, ProgressBar, SlurmScript } from "../components/primitives.jsx";

export default function JobsPage({ jobs, loading }) {
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
