// ─── tokens (duplicated from LandingPage to keep legal pages self-contained) ──
const T = {
  bg:     '#000000',
  bg2:    '#0a0a0a',
  border: '#2a2a2a',
  amber:  '#FFB866',
  text:   '#fafafa',
  muted:  '#6b6b6b',
}
const mono = "'DM Mono', 'Courier New', monospace"
const sans = "'DM Sans', system-ui, sans-serif"

// ─── nav ──────────────────────────────────────────────────────────────────────
function Nav() {
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 100,
      background: `${T.bg}f2`, backdropFilter: 'blur(14px)',
      borderBottom: `1px solid ${T.border}`,
    }}>
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '18px 48px', maxWidth: 1200, margin: '0 auto',
      }}>
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
          <img src="/logo.png" alt="ClusterPilot" width={28} height={28} style={{ display: 'block' }} />
          <span style={{ fontFamily: mono, fontSize: 16, color: T.amber }}>clusterpilot</span>
        </a>
        <a href="/" style={{ fontFamily: mono, fontSize: 13, color: T.muted, textDecoration: 'none' }}>
          ← back
        </a>
      </nav>
    </div>
  )
}

// ─── footer ───────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer style={{ background: T.bg, borderTop: `1px solid ${T.border}`, marginTop: 80 }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '32px 48px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 16 }}>
          <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
            <img src="/logo.png" alt="ClusterPilot" width={22} height={22} />
            <span style={{ fontFamily: mono, fontSize: 14, color: T.amber }}>clusterpilot</span>
          </a>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            {[
              ['Privacy Policy', '/privacy'],
              ['Terms of Service', '/terms'],
              ['Data Processing Agreement', '/dpa'],
              ['Acceptable Use Policy', '/acceptable-use'],
            ].map(([label, href]) => (
              <a key={label} href={href}
                style={{ fontFamily: mono, fontSize: 12, color: T.muted, textDecoration: 'none' }}
                onMouseEnter={e => e.currentTarget.style.color = T.text}
                onMouseLeave={e => e.currentTarget.style.color = T.muted}
              >
                {label}
              </a>
            ))}
          </div>
        </div>
      </div>
    </footer>
  )
}

// ─── layout ───────────────────────────────────────────────────────────────────
export default function LegalPage({ title, lastUpdated, children }) {
  return (
    <div style={{ background: T.bg, color: T.text, minHeight: '100vh', fontFamily: sans }}>
      <Nav />
      <main style={{ maxWidth: 780, margin: '0 auto', padding: '64px 48px 40px' }}>
        <p style={{ fontFamily: mono, fontSize: 12, color: T.muted, marginBottom: 12 }}>
          Legal · Frankly Labs
        </p>
        <h1 style={{ fontFamily: mono, fontSize: 28, color: T.amber, marginBottom: 8, fontWeight: 500 }}>
          {title}
        </h1>
        {lastUpdated && (
          <p style={{ fontFamily: mono, fontSize: 12, color: T.muted, marginBottom: 48 }}>
            Last updated: {lastUpdated}
          </p>
        )}
        <div style={{ lineHeight: 1.75, fontSize: 15 }}>
          {children}
        </div>
      </main>
      <Footer />
    </div>
  )
}

// ─── shared prose helpers ─────────────────────────────────────────────────────
export { T, mono, sans }

export function H2({ children }) {
  return (
    <h2 style={{
      fontFamily: mono, fontSize: 16, color: T.amber, fontWeight: 500,
      marginTop: 48, marginBottom: 12, letterSpacing: '0.02em',
    }}>
      {children}
    </h2>
  )
}

export function H3({ children }) {
  return (
    <h3 style={{
      fontFamily: mono, fontSize: 14, color: T.text, fontWeight: 500,
      marginTop: 28, marginBottom: 8,
    }}>
      {children}
    </h3>
  )
}

export function P({ children }) {
  return <p style={{ color: '#c8c8c8', marginBottom: 16 }}>{children}</p>
}

export function UL({ items }) {
  return (
    <ul style={{ color: '#c8c8c8', paddingLeft: 24, marginBottom: 16 }}>
      {items.map((item, i) => (
        <li key={i} style={{ marginBottom: 6 }}>{item}</li>
      ))}
    </ul>
  )
}

export function Table({ headers, rows }) {
  return (
    <div style={{ overflowX: 'auto', marginBottom: 24 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: 14 }}>
        <thead>
          <tr>
            {headers.map(h => (
              <th key={h} style={{
                textAlign: 'left', fontFamily: mono, fontSize: 12,
                color: T.muted, padding: '8px 16px 8px 0',
                borderBottom: `1px solid #2a2a2a`,
              }}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j} style={{
                  color: '#c8c8c8', padding: '10px 16px 10px 0',
                  borderBottom: `1px solid #1a1a1a`, verticalAlign: 'top',
                }}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function A({ href, children }) {
  return (
    <a href={href} target="_blank" rel="noreferrer"
      style={{ color: T.amber, textDecoration: 'none' }}
      onMouseEnter={e => e.currentTarget.style.textDecoration = 'underline'}
      onMouseLeave={e => e.currentTarget.style.textDecoration = 'none'}
    >
      {children}
    </a>
  )
}
