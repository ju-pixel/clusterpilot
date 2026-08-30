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
