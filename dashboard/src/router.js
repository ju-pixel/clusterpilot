// A four-route router, hand-rolled. react-router would be the reflex, but this
// app has three pages and one detail route, and Netlify already rewrites /* to
// index.html so deep links survive a refresh. Thirty lines beats a dependency
// for that.
import { useCallback, useEffect, useState } from "react";

const PAGES = new Set(["jobs", "notifications", "account"]);

export function parsePath(pathname) {
  const parts = pathname.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts.length === 0) return { page: "jobs" };
  if (parts[0] === "jobs" && parts.length >= 3) {
    return { page: "job", cluster: parts[1], id: parts[2] };
  }
  if (PAGES.has(parts[0])) return { page: parts[0] };
  return { page: "jobs" };
}

export function jobPath(job) {
  return `/jobs/${encodeURIComponent(job.cluster_name)}/${encodeURIComponent(job.slurm_job_id)}`;
}

export function useRoute() {
  const [route, setRoute] = useState(() => parsePath(window.location.pathname));

  useEffect(() => {
    const onPop = () => setRoute(parsePath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((path) => {
    if (path === window.location.pathname) return;
    window.history.pushState(null, "", path);
    setRoute(parsePath(path));
    window.scrollTo(0, 0);
  }, []);

  return [route, navigate];
}
