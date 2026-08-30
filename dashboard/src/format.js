// Formatting helpers. Pure functions, no React, so they can be reasoned
// about (and one day tested) on their own.
export function walltimeToSeconds(s) {
  if (!s) return 0;
  const parts = s.split(":").map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return 0;
}

export function walltimePct(consumed, requested) {
  const c = walltimeToSeconds(consumed);
  const r = walltimeToSeconds(requested);
  if (!r || !c) return 0;
  return Math.min(100, Math.round((c / r) * 100));
}

export function formatDatetime(iso) {
  if (!iso) return "─";
  const d = new Date(iso);
  if (isNaN(d)) return "─";
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

// ── Primitives ────────────────────────────────────────────────────────────────


// "updated 12s ago". Deliberately coarse: the point is to say whether what
// you are looking at is current, not to tick like a stopwatch.
export function formatAge(ms) {
  if (ms == null) return "never";
  const s = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  return `${Math.round(m / 60)}h ago`;
}

// Reserved resource time, stored in seconds and read in hours.
export function formatHours(seconds) {
  if (seconds == null) return null;
  const hours = seconds / 3600;
  if (hours === 0) return "0";
  if (hours < 0.1) return "<0.1";
  if (hours < 10) return hours.toFixed(1);
  return Math.round(hours).toLocaleString();
}

// SLURM reports "<exit>:<signal>". A signal is the more explanatory half when
// there is one, because it says the job was killed rather than that it chose
// to stop.
export function describeExit(code) {
  if (!code) return null;
  const [exit, signal] = code.split(":");
  if (Number(signal)) return `killed by signal ${signal}`;
  if (Number(exit)) return `exit code ${exit}`;
  return "exit 0";
}


// Lines worth surfacing from a log tail. Deliberately narrow: the point is to
// answer "what went wrong" at a glance, and a pattern that matches half the
// log would put noise in every row instead.
const ERROR_LINE = /\b(error|fatal|traceback|segmentation fault|out of memory|oom|killed|cannot|no such file|not found|permission denied|command not found)\b/i;

// The first line of a failed job's log that looks like the reason, trimmed to
// fit one row. Returns null when nothing stands out, because a guessed reason
// is worse than none.
export function firstErrorLine(logTail, limit = 90) {
  if (!logTail) return null;
  for (const raw of logTail.split("\n")) {
    const line = raw.trim();
    if (!line || !ERROR_LINE.test(line)) continue;
    return line.length > limit ? `${line.slice(0, limit - 1)}…` : line;
  }
  return null;
}
