// Live job list. Its own hook so the shell stays a layout component and the
// polling rules live in one place.
import { useCallback, useEffect, useRef, useState } from "react";

import { makeApiClient } from "./api.js";

// The daemon polls the cluster on its own schedule and pushes state changes,
// so refreshing faster than this buys nothing but requests.
const POLL_MS = 20_000;

export function useJobs(isSignedIn, getToken) {
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  // Older pages are appended and then left alone: refreshing re-fetches only
  // the newest page, because that is where anything changes.
  const [older, setOlder] = useState([]);
  const [exhausted, setExhausted] = useState(false);
  const [loadingOlder, setLoadingOlder] = useState(false);

  // Kept in a ref so the polling effect does not restart on every fetch.
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    if (!isSignedIn || inFlight.current) return;
    inFlight.current = true;
    setRefreshing(true);
    try {
      const data = await makeApiClient(getToken).getJobs();
      setJobs(data);
      setFetchedAt(Date.now());
      setError(null);
    } catch (err) {
      // Keep showing the last good list: a stale list with an honest "as of"
      // is more use than an empty screen, and the stamp stops updating so the
      // staleness is visible rather than implied.
      setError(err.message || "Could not reach the API");
    } finally {
      inFlight.current = false;
      setRefreshing(false);
      setLoading(false);
    }
  }, [isSignedIn, getToken]);

  useEffect(() => {
    if (!isSignedIn) return undefined;
    refresh();

    let timer = null;
    const start = () => {
      if (timer === null) timer = setInterval(refresh, POLL_MS);
    };
    const stop = () => {
      if (timer !== null) { clearInterval(timer); timer = null; }
    };

    // A backgrounded tab does not need to poll, and a laptop that has been
    // shut all night should not wake up to a burst of queued intervals.
    // Refresh once on the way back so the first thing seen is current.
    const onVisibility = () => {
      if (document.visibilityState === "visible") { refresh(); start(); }
      else stop();
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => { stop(); document.removeEventListener("visibilitychange", onVisibility); };
  }, [isSignedIn, refresh]);

  // One page older than whatever is on screen. A button, not infinite scroll:
  // scroll hijacking fights the back button, and now that a job has its own
  // URL it would make a job's position unreproducible.
  const loadOlder = useCallback(async () => {
    if (loadingOlder || exhausted) return;
    const all = [...jobs, ...older];
    const oldest = all[all.length - 1]?.submitted_at;
    if (!oldest) { setExhausted(true); return; }
    setLoadingOlder(true);
    try {
      const page = await makeApiClient(getToken).getJobs(oldest);
      if (page.length === 0) setExhausted(true);
      else setOlder(prev => [...prev, ...page]);
    } catch (err) {
      setError(err.message || "Could not load older jobs");
    } finally {
      setLoadingOlder(false);
    }
  }, [jobs, older, loadingOlder, exhausted, getToken]);

  // The newest page can overtake what was paged in earlier, so anything the
  // refresh already returned is dropped from the older pages rather than
  // rendered twice.
  const newestKeys = new Set(jobs.map(j => `${j.cluster_name}/${j.slurm_job_id}`));
  const combined = [
    ...jobs,
    ...older.filter(j => !newestKeys.has(`${j.cluster_name}/${j.slurm_job_id}`)),
  ];

  return {
    jobs: combined, loading, error, fetchedAt, refreshing, refresh,
    loadOlder, loadingOlder, exhausted,
  };
}
