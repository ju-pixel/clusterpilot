// Dashboard shell: auth, the subscribe gate, the nav, and the job fetch
// every page below hangs off. Pages live in src/pages/, shared bits in
// src/components/, tokens in src/theme.js.
import { useState, useEffect } from "react";
import { RedirectToSignIn, useUser, useAuth, useClerk } from "@clerk/react";

import { makeApiClient } from "./api.js";
import { useJobs } from "./useJobs.js";
import { T, CLUSTER_META, btnStyle } from "./theme.js";
import { NAV } from "./nav.js";
import { formatAge } from "./format.js";
import { Glow, Dot, SectionLabel } from "./components/primitives.jsx";
import { useRoute } from "./router.js";
import JobsPage from "./pages/JobsPage.jsx";
import JobDetailPage from "./pages/JobDetailPage.jsx";
import NotificationsPage from "./pages/NotificationsPage.jsx";
import AccountPage from "./pages/AccountPage.jsx";
import SubscribeGate from "./pages/SubscribeGate.jsx";

export default function ClusterPilotDashboard() {
  const [route, navigate] = useRoute();
  // The detail page is still "Jobs" as far as the sidebar is concerned.
  const activeNav = route.page === "job" ? "jobs" : route.page;
  const [userInfo, setUserInfo] = useState(null);
  // Re-rendered on a timer purely so the "updated Ns ago" stamp counts up.
  const [, setTick] = useState(0);

  const { isSignedIn, isLoaded, getToken } = useAuth();
  const { user } = useUser();
  const { signOut } = useClerk();
  const email = user?.primaryEmailAddress?.emailAddress ?? "";

  const {
    jobs, loading: jobsLoading, error: jobsError,
    fetchedAt, refreshing, refresh,
    loadOlder, loadingOlder, exhausted,
  } = useJobs(isSignedIn, getToken);

  useEffect(() => {
    if (!isSignedIn) return;
    makeApiClient(getToken).getMe().then(setUserInfo).catch(() => {});
  }, [isSignedIn, getToken]);

  useEffect(() => {
    const id = setInterval(() => setTick(n => n + 1), 5000);
    return () => clearInterval(id);
  }, []);

  // Not null: rendering nothing leaves the browser painting its own white,
  // which on a dark app looks like a crash rather than a wait.
  if (!isLoaded) {
    return (
      <div style={{
        minHeight: "100vh", background: T.bg, color: T.dim,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontFamily: T.sans, fontSize: 15,
      }}>Loading...</div>
    );
  }
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
      // The shell is an app frame, not a document: the topbar and sidebar stay
      // put and each pane scrolls inside itself. That only works if the frame
      // is bounded to the viewport. With min-height it was free to grow, so a
      // long page (a job's Logs tab, #64) stretched the whole shell instead of
      // scrolling its own pane, and no scrollbar ever appeared. dvh rather
      // than vh so a phone's collapsing address bar does not cut the bottom off.
      height: "100dvh",
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
        <Glow color={T.amberText} style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 700, letterSpacing: "0.18em" }}>
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
              <button key={item.id} onClick={() => navigate(`/${item.id}`)} style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "10px 16px",
                background: active ? `${T.amber}0f` : "transparent",
                borderLeft: `2px solid ${active ? T.amber : "transparent"}`,
                border: "none", cursor: "pointer", width: "100%", textAlign: "left",
                color: active ? T.amberText : T.dim,
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
                      ? <><Glow color={T.amberText} style={{ fontSize: 13 }}>{c.pending}</Glow> pending</>
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
                <Glow color={T.amberText} style={{ fontFamily: T.mono, fontSize: 20, fontWeight: 700, display: "block" }}>
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
            display: "flex", alignItems: "center", justifyContent: "space-between", gap: 16,
          }}>
            <h1 style={{ margin: 0, fontFamily: T.sans, fontSize: 20, fontWeight: 600, color: T.text }}>
              {route.page === "job"
                ? "Job"
                : NAV.find(n => n.id === activeNav)?.label}
            </h1>
            {(route.page === "jobs" || route.page === "job") && (
              <Freshness
                fetchedAt={fetchedAt}
                refreshing={refreshing}
                error={jobsError}
                onRefresh={refresh}
              />
            )}
          </div>

          {/* page content */}
          <div style={{ flex: 1, overflow: "auto", display: "flex" }}>
            {route.page === "jobs" && (
              <JobsPage
                jobs={jobs} loading={jobsLoading} navigate={navigate}
                onLoadOlder={loadOlder} loadingOlder={loadingOlder}
                exhausted={exhausted}
              />
            )}
            {route.page === "job" && (
              <JobDetailPage
                job={jobs.find(j =>
                  String(j.slurm_job_id) === route.id && j.cluster_name === route.cluster
                ) ?? null}
                loading={jobsLoading}
                navigate={navigate}
              />
            )}
            {route.page === "notifications" && <NotificationsPage />}
            {route.page === "account"       && <AccountPage email={email} userInfo={userInfo} />}
          </div>
        </div>
      </div>
    </div>
  );
}


// Says how old the list on screen is, because a job monitor that silently
// stops updating is worse than one that admits it. The stamp stops advancing
// when a refresh fails, which is the signal that something is wrong.
function Freshness({ fetchedAt, refreshing, error, onRefresh }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <span style={{
        fontFamily: T.sans, fontSize: 13,
        color: error ? T.red : T.dim,
      }}>
        {error
          ? `not updating: ${error}`
          : refreshing ? "updating..." : `updated ${formatAge(fetchedAt)}`}
      </span>
      <button
        onClick={onRefresh}
        disabled={refreshing}
        style={{ ...btnStyle, padding: "5px 11px", fontSize: 14,
                 cursor: refreshing ? "default" : "pointer" }}
      >
        Refresh
      </button>
    </div>
  );
}
