import { T } from "../theme.js";

export function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 28 }}>
      <div style={{
        fontFamily: T.sans, fontSize: 15, fontWeight: 600,
        color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em",
        marginBottom: 12, paddingBottom: 8,
        borderBottom: `1px solid ${T.border}`,
      }}>{title}</div>
      {children}
    </div>
  );
}
