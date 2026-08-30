import { useState } from "react";
import { useClerk } from "@clerk/react";

import { makeApiClient } from "../api.js";
import { T, btnStyle } from "../theme.js";
import { Glow } from "../components/primitives.jsx";

const PLANS = {
  month: { label: "Monthly", price: "$6 / month", seat: "$5.10 / month", note: null },
  year:  { label: "Annual",  price: "$60 / year", seat: "$51 / year",    note: "two months free" },
};

// Switch between the monthly and annual price. `field` picks the PLANS line
// shown under the label: "price" for a researcher seat, "seat" for a group seat.
function IntervalToggle({ value, onChange, field }) {
  return (
    <div role="radiogroup" aria-label="Billing interval" style={{ display: "flex", gap: 8 }}>
      {Object.entries(PLANS).map(([key, plan]) => {
        const on = key === value;
        return (
          <button
            key={key}
            role="radio"
            aria-checked={on}
            onClick={() => onChange(key)}
            style={{
              flex: 1, padding: "10px 12px", textAlign: "left", cursor: "pointer",
              background: on ? `${T.amber}14` : T.panel2,
              border: `1.5px solid ${on ? T.amber : T.border2}`, borderRadius: 6,
            }}
          >
            <div style={{ fontFamily: T.sans, fontSize: 15, fontWeight: 600, color: on ? T.text : T.muted }}>
              {plan.label}
            </div>
            <div style={{ fontFamily: T.mono, fontSize: 13, color: on ? T.amberText : T.dim, marginTop: 2 }}>
              {plan[field]}{plan.note ? `, ${plan.note}` : ""}
            </div>
          </button>
        );
      })}
    </div>
  );
}

export default function SubscribeGate({ email, getToken }) {
  const api = makeApiClient(getToken);
  const { signOut } = useClerk();
  const [billingInterval, setBillingInterval] = useState("month");
  const [loading, setLoading] = useState(false);
  const [piLoading, setPiLoading] = useState(false);
  const [piQty, setPiQty] = useState(3);
  const [groupInterval, setGroupInterval] = useState("month");
  const [redeemMode, setRedeemMode] = useState(false);
  const [redeemCode, setRedeemCode] = useState("");
  const [redeemLoading, setRedeemLoading] = useState(false);
  const [redeemError, setRedeemError] = useState(null);
  const [checkoutError, setCheckoutError] = useState(null);

  async function handleSubscribe() {
    setLoading(true);
    setCheckoutError(null);
    try {
      const { url } = await api.createCheckout(billingInterval);
      window.location.href = url;
    } catch (err) {
      console.error("createCheckout failed:", err);
      setCheckoutError(err.message || "Could not start checkout. Please try again.");
      setLoading(false);
    }
  }

  async function handlePiCheckout() {
    setPiLoading(true);
    setCheckoutError(null);
    try {
      const { url } = await api.createPiCheckout(piQty, groupInterval);
      window.location.href = url;
    } catch (err) {
      console.error("createPiCheckout failed:", err);
      setCheckoutError(err.message || "Could not start checkout. Please try again.");
      setPiLoading(false);
    }
  }

  async function handleRedeem() {
    setRedeemLoading(true);
    setRedeemError(null);
    try {
      await api.redeemInvite(redeemCode.trim());
      window.location.reload();
    } catch (err) {
      setRedeemError(err.message || "Invalid or already-used code.");
      setRedeemLoading(false);
    }
  }

  return (
    <div style={{
      background: T.bg, minHeight: "100vh", display: "flex",
      flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: T.sans, padding: "0 24px",
    }}>
      <Glow color={T.amberText} style={{ fontFamily: T.mono, fontSize: 17, fontWeight: 700, letterSpacing: "0.18em", marginBottom: 40 }}>
        ◈ CLUSTERPILOT
      </Glow>

      {redeemMode ? (
        <div style={{
          background: T.panel, border: `1px solid ${T.border2}`,
          borderRadius: 10, padding: "36px 40px", maxWidth: 460, width: "100%",
        }}>
          <h2 style={{ margin: "0 0 8px", fontFamily: T.sans, fontSize: 22, fontWeight: 700, color: T.text }}>
            Redeem invite code
          </h2>
          <p style={{ margin: "0 0 20px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
            Enter the code your PI shared with you.
          </p>
          <input
            value={redeemCode}
            onChange={e => setRedeemCode(e.target.value.toUpperCase())}
            placeholder="e.g. A3F2B891"
            style={{
              width: "100%", boxSizing: "border-box",
              background: T.panel2, border: `1px solid ${T.border2}`,
              borderRadius: 5, padding: "10px 12px", marginBottom: 12,
              fontFamily: T.mono, fontSize: 18, color: T.text,
              letterSpacing: "0.1em", textAlign: "center",
            }}
          />
          {redeemError && (
            <div style={{
              background: T.redDim, border: `1px solid ${T.red}55`,
              borderRadius: 5, padding: "8px 12px", marginBottom: 12,
              fontFamily: T.mono, fontSize: 13, color: T.red,
            }}>{redeemError}</div>
          )}
          <button
            onClick={handleRedeem}
            disabled={redeemLoading || !redeemCode.trim()}
            style={{
              width: "100%", padding: "12px 0",
              background: T.amber, border: "none", borderRadius: 6,
              fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.ink,
              cursor: (redeemLoading || !redeemCode.trim()) ? "not-allowed" : "pointer",
              opacity: (redeemLoading || !redeemCode.trim()) ? 0.7 : 1,
            }}
          >
            {redeemLoading ? "Checking..." : "Redeem →"}
          </button>
          <button
            onClick={() => setRedeemMode(false)}
            style={{ ...btnStyle, width: "100%", marginTop: 10, textAlign: "center" }}
          >
            Back
          </button>
        </div>
      ) : (
        <>
          {checkoutError && (
            <div style={{
              background: T.redDim, border: `1px solid ${T.red}55`,
              borderRadius: 6, padding: "10px 14px",
              maxWidth: 460, width: "100%", marginBottom: 16,
              fontFamily: T.mono, fontSize: 13, color: T.red,
              wordBreak: "break-word",
            }}>{checkoutError}</div>
          )}
          <div style={{
            background: T.panel, border: `1px solid ${T.border2}`,
            borderRadius: 10, padding: "36px 40px", maxWidth: 460, width: "100%",
            marginBottom: 16,
          }}>
            <h2 style={{ margin: "0 0 8px", fontFamily: T.sans, fontSize: 22, fontWeight: 700, color: T.text }}>
              Start your free trial
            </h2>
            <p style={{ margin: "0 0 20px", fontFamily: T.sans, fontSize: 16, color: T.dim }}>
              14 days free, then {PLANS[billingInterval].price}. Founding price, locked for the first 50 subscribers. Cancel any time.
            </p>
            <div style={{ marginBottom: 24 }}>
              <IntervalToggle value={billingInterval} onChange={setBillingInterval} field="price" />
            </div>
            <div style={{ marginBottom: 28 }}>
              {[
                "Managed API key — no Anthropic account needed",
                "Web dashboard for all job history",
                "Multi-machine sync — one view across all clusters",
                "Priority support",
              ].map(f => (
                <div key={f} style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                  <span style={{ color: T.amberText, fontFamily: T.mono, fontSize: 14 }}>✓</span>
                  <span style={{ fontFamily: T.sans, fontSize: 15, color: T.muted }}>{f}</span>
                </div>
              ))}
            </div>
            <button
              onClick={handleSubscribe}
              disabled={loading}
              style={{
                width: "100%", padding: "12px 0",
                background: T.amber, border: "none", borderRadius: 6,
                fontFamily: T.sans, fontSize: 16, fontWeight: 600, color: T.ink,
                cursor: loading ? "not-allowed" : "pointer",
                opacity: loading ? 0.7 : 1,
              }}
            >
              {loading ? "Redirecting..." : "Start free trial →"}
            </button>
            <p style={{ margin: "14px 0 0", fontFamily: T.mono, fontSize: 13, color: T.dim, textAlign: "center" }}>
              {email}
            </p>
          </div>

          <div style={{
            background: T.panel, border: `1px solid ${T.border2}`,
            borderRadius: 10, padding: "28px 40px", maxWidth: 460, width: "100%",
          }}>
            <h3 style={{ margin: "0 0 6px", fontFamily: T.sans, fontSize: 17, fontWeight: 600, color: T.text }}>
              Buying for your group?
            </h3>
            <p style={{ margin: "0 0 14px", fontFamily: T.sans, fontSize: 15, color: T.dim }}>
              15% off for 3 or more seats, monthly or yearly. You get one invite code per seat to share with your researchers.
            </p>
            <div style={{ marginBottom: 12 }}>
              <IntervalToggle value={groupInterval} onChange={setGroupInterval} field="seat" />
            </div>
            <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 12 }}>
              <label style={{ fontFamily: T.sans, fontSize: 15, color: T.muted, whiteSpace: "nowrap" }}>
                Seats:
              </label>
              <input
                type="number"
                min={3}
                value={piQty}
                onChange={e => setPiQty(Math.max(3, parseInt(e.target.value) || 3))}
                style={{
                  width: 70, background: T.panel2, border: `1px solid ${T.border2}`,
                  borderRadius: 5, padding: "7px 10px",
                  fontFamily: T.mono, fontSize: 15, color: T.text, textAlign: "center",
                }}
              />
              <span style={{ fontFamily: T.mono, fontSize: 14, color: T.dim }}>
                × {PLANS[groupInterval].seat}
              </span>
            </div>
            <button
              onClick={handlePiCheckout}
              disabled={piLoading}
              style={{
                width: "100%", padding: "11px 0",
                background: "transparent", border: `1.5px solid ${T.amber}`,
                borderRadius: 6, fontFamily: T.sans, fontSize: 16, fontWeight: 600,
                color: T.amberText, cursor: piLoading ? "not-allowed" : "pointer",
                opacity: piLoading ? 0.7 : 1,
              }}
            >
              {piLoading ? "Redirecting..." : "Buy group seats →"}
            </button>
            <p style={{ margin: "12px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim, textAlign: "center" }}>
              Have a code from your PI?{" "}
              <span
                onClick={() => setRedeemMode(true)}
                style={{ color: T.amberText, cursor: "pointer", textDecoration: "underline" }}
              >
                Redeem it here
              </span>
            </p>
          </div>
        </>
      )}

      <p style={{ margin: "28px 0 0", fontFamily: T.sans, fontSize: 14, color: T.dim, textAlign: "center" }}>
        Signed in as {email}.{" "}
        <span
          onClick={() => signOut({ redirectUrl: "https://clusterpilot.sh" })}
          style={{ color: T.amberText, cursor: "pointer", textDecoration: "underline" }}
        >
          Sign out or use a different account
        </span>
      </p>
    </div>
  );
}
