// Dashboard shell: auth, the subscribe gate, the nav, and the job fetch
// every page below hangs off. Pages live in src/pages/, shared bits in
// src/components/, tokens in src/theme.js.
import { useState, useEffect } from "react";
import { RedirectToSignIn, useUser, useAuth, useClerk } from "@clerk/react";

import { makeApiClient } from "./api.js";
import { T, CLUSTER_META } from "./theme.js";
import { NAV } from "./nav.js";
import JobsPage from "./pages/JobsPage.jsx";
import NotificationsPage from "./pages/NotificationsPage.jsx";
import AccountPage from "./pages/AccountPage.jsx";
import SubscribeGate from "./pages/SubscribeGate.jsx";

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
