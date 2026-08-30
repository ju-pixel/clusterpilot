import { useState, useEffect } from "react";
import { useAuth } from "@clerk/react";

import { makeApiClient } from "../api.js";
import { T, btnStyle } from "../theme.js";
import { SectionLabel } from "../components/primitives.jsx";
import { Section } from "../components/layout.jsx";

function describePlan({ amount, currency, interval, quantity }) {
  if (quantity > 1) return `${quantity} seats, billed ${interval === "year" ? "yearly" : "monthly"}`;
  const units = amount / 100;
  const number = Number.isInteger(units) ? String(units) : units.toFixed(2);
  const money = currency === "usd" ? `$${number}` : `${number} ${currency.toUpperCase()}`;
  return `${money} / ${interval}`;
}

export default function AccountPage({ email, userInfo }) {
  const { getToken } = useAuth();
  const api = makeApiClient(getToken);

  const [keyInfo, setKeyInfo] = useState(undefined); // undefined = loading, null = no key
  const [subscription, setSubscription] = useState(null); // null = none, or not loaded
  const [rotating, setRotating] = useState(false);
  const [newKey, setNewKey] = useState(null); // shown once after issue/rotate
  const [billingLoading, setBillingLoading] = useState(false);
  const [keyError, setKeyError] = useState(null);
  const [billingError, setBillingError] = useState(null);
  const [invites, setInvites] = useState(null); // null = not loaded yet

  useEffect(() => {
    api.getKeys()
      .then(setKeyInfo)
      .catch(() => {
        // 404 means no key issued yet — that's a valid state
        setKeyInfo(null);
      });
    api.getInvites()
      .then(setInvites)
      .catch(() => setInvites([]));
    api.getSubscription()
      .then(setSubscription)
      .catch(() => setSubscription(null));
  }, []);

  async function handleIssueOrRotate() {
    setRotating(true);
    setNewKey(null);
    setKeyError(null);
    try {
      const result = keyInfo === null
        ? await api.issueKey()
        : await api.rotateKey();
      setNewKey(result.key);
      setKeyInfo(result);
    } catch (err) {
      setKeyError(err.message || "Request failed.");
    } finally {
      setRotating(false);
    }
  }

  async function handleBillingPortal() {
    setBillingLoading(true);
    setBillingError(null);
    try {
      const { url } = await api.getBillingPortal();
      window.location.href = url;
    } catch (err) {
      setBillingError(err.message || "Could not open billing portal.");
      setBillingLoading(false);
    }
  }

  const hasKey = keyInfo !== null && keyInfo !== undefined;
  const keyDisplay = newKey ?? (hasKey ? keyInfo.key : keyInfo === undefined ? "Loading..." : "No key issued yet");

  return (
    <div style={{ padding: "28px 32px", maxWidth: 560 }}>
      <h2 style={{ margin: "0 0 4px", fontFamily: T.sans, fontSize: 22, fontWeight: 600, color: T.text }}>
        Account
      </h2>
      <p style={{ margin: "0 0 28px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
        {email}
      </p>

      {/* trial banner */}
      {userInfo?.subscription_status === "trialing" && (
        <div style={{
          background: T.amberLo, border: `1px solid ${T.amber}55`,
          borderRadius: 6, padding: "10px 14px", marginBottom: 24,
          fontFamily: T.sans, fontSize: 15, color: T.amber,
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{ fontFamily: T.mono }}>◈</span>
          You are on a 14-day free trial. No charge until the trial ends.
        </div>
      )}

      {/* managed API key */}
      <Section title="Managed API Key">
        <p style={{ margin: "0 0 12px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
          ClusterPilot uses this key for SLURM script generation. You do not need your own Anthropic account.
        </p>
        {newKey && (
          <div style={{
            background: T.amberLo, border: `1px solid ${T.amber}44`,
            borderRadius: 5, padding: "8px 12px", marginBottom: 10,
            fontFamily: T.sans, fontSize: 14, color: T.amber,
          }}>
            Copy this key now — it will not be shown again.
          </div>
        )}
        {keyError && (
          <div style={{
            background: T.redDim, border: `1px solid ${T.red}55`,
            borderRadius: 5, padding: "8px 12px", marginBottom: 10,
            fontFamily: T.mono, fontSize: 13, color: T.red,
          }}>
            {keyError}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <div style={{
            flex: 1, background: T.panel2, border: `1px solid ${T.border2}`,
            borderRadius: 5, padding: "8px 12px",
            fontFamily: T.mono, fontSize: 15, color: T.dim,
            letterSpacing: "0.05em", wordBreak: "break-all",
          }}>{keyDisplay}</div>
          {newKey && (
            <button onClick={() => navigator.clipboard.writeText(newKey)} style={btnStyle}>
              Copy
            </button>
          )}
          <button onClick={handleIssueOrRotate} disabled={rotating || keyInfo === undefined} style={btnStyle}>
            {rotating ? "..." : hasKey ? "Rotate" : "Issue key"}
          </button>
        </div>
        <p style={{ margin: "6px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim }}>
          {hasKey
            ? "Rotating issues a new key and invalidates the current one immediately."
            : "Issue a key to start using the managed API from the ClusterPilot TUI."}
        </p>
      </Section>

      {/* subscription */}
      <Section title="Subscription">
        <div style={{
          background: T.panel2, border: `1px solid ${T.border2}`,
          borderRadius: 6, padding: "14px 16px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontFamily: T.sans, fontSize: 17, fontWeight: 600, color: T.text }}>
              Researcher{" "}
              {subscription && (
                <span style={{ fontFamily: T.mono, fontSize: 15, color: T.amber }}>{describePlan(subscription)}</span>
              )}
            </div>
            <div style={{ fontFamily: T.sans, fontSize: 15, color: T.dim, marginTop: 3 }}>
              {userInfo?.subscription_status === "trialing" ? "Free trial active"
                : userInfo?.subscription_status === "active" ? "Active"
                : userInfo?.subscription_status ?? "loading..."}
            </div>
          </div>
          <button onClick={handleBillingPortal} disabled={billingLoading} style={btnStyle}>
            {billingLoading ? "..." : "Manage billing ↗"}
          </button>
        </div>
        {billingError && (
          <div style={{
            background: T.redDim, border: `1px solid ${T.red}55`,
            borderRadius: 5, padding: "8px 12px", marginTop: 8,
            fontFamily: T.mono, fontSize: 13, color: T.red,
          }}>
            {billingError}
          </div>
        )}
      </Section>

      {/* group seats — only shown if this user has issued invite codes */}
      {invites !== null && invites.length > 0 && (
        <Section title="Group Seats">
          <p style={{ margin: "0 0 14px", fontFamily: T.sans, fontSize: 15, color: T.dim }}>
            {invites.filter(c => c.redeemed).length} of {invites.length} seats redeemed.
          </p>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {invites.map(invite => (
              <div key={invite.code} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                background: T.panel2, border: `1px solid ${T.border2}`,
                borderRadius: 5, padding: "8px 14px",
              }}>
                <span style={{ fontFamily: T.mono, fontSize: 16, letterSpacing: "0.1em", color: T.text }}>
                  {invite.code}
                </span>
                <span style={{
                  fontFamily: T.mono, fontSize: 13,
                  color: invite.redeemed ? T.cyan : T.dim,
                }}>
                  {invite.redeemed ? "redeemed" : "pending"}
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {/* danger zone */}
      <Section title="Danger Zone">
        <div style={{
          background: `${T.red}08`, border: `1px solid ${T.red}33`,
          borderRadius: 6, padding: "14px 16px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div>
            <div style={{ fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.red }}>
              Cancel subscription
            </div>
            <div style={{ fontFamily: T.sans, fontSize: 15, color: T.dim, marginTop: 2 }}>
              Revokes managed API key at period end. Local tool still works.
            </div>
          </div>
          <button
            onClick={handleBillingPortal}
            style={{ ...btnStyle, background: T.redDim, border: `1px solid ${T.red}66`, color: T.red }}
          >
            Cancel
          </button>
        </div>
      </Section>
    </div>
  );
}

// shared section wrapper used in Account page
