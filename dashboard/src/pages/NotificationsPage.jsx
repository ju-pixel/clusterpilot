import { useState, useEffect } from "react";
import { useAuth } from "@clerk/react";

import { makeApiClient } from "../api.js";
import { T, btnStyle } from "../theme.js";
import { SectionLabel } from "../components/primitives.jsx";
import { Section } from "../components/layout.jsx";

export default function NotificationsPage() {
  const { getToken } = useAuth();
  const api = makeApiClient(getToken);

  const [prefs, setPrefs] = useState(null);
  const [topic, setTopic] = useState("");
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getNotifyPrefs()
      .then(data => {
        setPrefs(data);
        setTopic(data.ntfy_topic ?? "");
      })
      .catch(() => {});
  }, []);

  async function handleToggle(key) {
    if (!prefs) return;
    const updated = { ...prefs, [key]: !prefs[key] };
    setPrefs(updated);
    try {
      await api.updateNotifyPrefs(updated);
    } catch {
      setPrefs(prefs); // revert on error
    }
  }

  async function handleSaveTopic() {
    if (!prefs) return;
    setSaving(true);
    try {
      const updated = { ...prefs, ntfy_topic: topic || null };
      await api.updateNotifyPrefs(updated);
      setPrefs(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  const TOGGLES = [
    { label: "Job starts running",  sub: "PENDING → RUNNING",              key: "notify_on_start"         },
    { label: "Job completes",       sub: "RUNNING → COMPLETED",            key: "notify_on_complete"      },
    { label: "Job fails",           sub: "RUNNING → FAILED / TIMEOUT",     key: "notify_on_fail"          },
    { label: "Walltime warning",    sub: "less than 30 minutes remaining",  key: "notify_on_walltime_warn" },
  ];

  return (
    <div style={{ padding: "28px 32px", maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 4px", fontFamily: T.sans, fontSize: 22, fontWeight: 600, color: T.text }}>
        Notifications
      </h2>
      <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
        These settings control which events your local ClusterPilot daemon sends,
        via ntfy.sh or any compatible webhook. The daemon reads them when it starts,
        so restart it to pick up a change straight away. Nothing is sent from here.
      </p>

      {/* ntfy topic */}
      <div style={{ marginBottom: 24 }}>
        <label style={{ display: "block", fontFamily: T.sans, fontSize: 15, fontWeight: 600, color: T.muted, marginBottom: 6 }}>
          ntfy.sh topic URL
        </label>
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={topic}
            onChange={e => setTopic(e.target.value)}
            placeholder="https://ntfy.sh/your-topic"
            style={{
              flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
              borderRadius: 5, padding: "8px 12px",
              fontFamily: T.mono, fontSize: 15, color: T.text,
              outline: "none",
            }}
          />
          <button
            onClick={() => { if (topic) navigator.clipboard.writeText(topic); }}
            style={btnStyle}
          >
            Copy
          </button>
          <button onClick={handleSaveTopic} disabled={saving} style={btnStyle}>
            {saved ? "Saved" : saving ? "Saving..." : "Save"}
          </button>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim }}>
          When set, the daemon posts here instead of the topic in your config.toml.
        </p>
        {topic && (
          <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim }}>
            Subscribe on any device:{" "}
            <span style={{ fontFamily: T.mono, color: T.muted }}>
              ntfy subscribe {topic.split("/").pop()}
            </span>
          </p>
        )}
      </div>

      {/* event toggles */}
      <div>
        <div style={{ fontFamily: T.sans, fontSize: 15, fontWeight: 600, color: T.muted, marginBottom: 12 }}>
          The daemon sends a notification when
        </div>
        {TOGGLES.map(item => {
          const on = prefs ? prefs[item.key] : false;
          return (
            <div key={item.key} style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "12px 16px",
              background: T.panel2, border: `1px solid ${T.border}`,
              borderRadius: 6, marginBottom: 8,
            }}>
              <div>
                <div style={{ fontFamily: T.sans, fontSize: 16, color: T.text }}>{item.label}</div>
                <div style={{ fontFamily: T.mono, fontSize: 14, color: T.dim, marginTop: 2 }}>{item.sub}</div>
              </div>
              <div
                onClick={() => handleToggle(item.key)}
                style={{
                  width: 40, height: 22, borderRadius: 11,
                  background: on ? T.amber : T.border2,
                  position: "relative", cursor: "pointer", flexShrink: 0,
                  transition: "background 0.2s",
                }}
              >
                <div style={{
                  position: "absolute", top: 3,
                  left: on ? 20 : 3,
                  width: 16, height: 16, borderRadius: "50%",
                  background: T.text, transition: "left 0.2s",
                }} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// The plan as Stripe reports it: "$6 / month", "$60 / year", or for a PI
// bundle "3 seats, billed monthly" (the seat price carries the group discount,
// which the portal shows exactly).
