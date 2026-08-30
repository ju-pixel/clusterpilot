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

  return { jobs, loading, error, fetchedAt, refreshing, refresh };
}
