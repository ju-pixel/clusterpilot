// ─── tokens ─────────────────────────────────────────────────────────────────
// Shared design tokens (see ../theme.js). This used to be a local copy of its
// own; it now draws from the same single source of truth as every other page.
import { T, F, mono, sans } from '../theme'

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
          {/* 40px mark + 22px wordmark, weight 500. Matches every CP header;
              see the note in LandingPage's Nav for why 40 and not FN's 34. */}
          <img src="/logo.png" alt="ClusterPilot" width={40} height={40} style={{ display: 'block' }} />
          <span style={{ fontFamily: mono, fontSize: 22, fontWeight: 500, color: T.amberText, letterSpacing: '-0.3px' }}>clusterpilot</span>
        </a>
        <a href="/" style={{ fontFamily: mono, fontSize: F.label, color: T.muted, textDecoration: 'none' }}>
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
            <span style={{ fontFamily: mono, fontSize: F.note, color: T.amberText }}>clusterpilot</span>
          </a>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            {[
              ['Privacy Policy', '/privacy'],
              ['Terms of Service', '/terms'],
              ['Data Processing Agreement', '/dpa'],
              ['Acceptable Use Policy', '/acceptable-use'],
            ].map(([label, href]) => (
              <a key={label} href={href}
                style={{ fontFamily: mono, fontSize: F.note, color: T.muted, textDecoration: 'none' }}
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
        <p style={{ fontFamily: mono, fontSize: F.legal, color: T.muted, marginBottom: 12 }}>
          Legal · Frankly Labs
        </p>
        {/* 32, not the hero's clamp up to 58: a legal page title sits at the top
            of a compressed mono hierarchy (H1 32 / H2 20 / H3 18 / body 17). */}
        <h1 style={{ fontFamily: mono, fontSize: 32, color: T.amberText, marginBottom: 8, fontWeight: 500 }}>
          {title}
        </h1>
        {lastUpdated && (
          <p style={{ fontFamily: mono, fontSize: F.legal, color: T.muted, marginBottom: 48 }}>
            Last updated: {lastUpdated}
          </p>
        )}
        <div style={{ lineHeight: 1.75, fontSize: F.item }}>
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
      // 20, not the landing page's 40: this is a numbered clause heading in a
      // dense legal document, not a marketing section header. The B.2 scale's
      // H1/H2 sizes were written for the hero and do not transfer here.
      fontFamily: mono, fontSize: F.body, color: T.amberText, fontWeight: 500,
      marginTop: 48, marginBottom: 12, letterSpacing: '0.02em',
    }}>
      {children}
    </h2>
  )
}

export function H3({ children }) {
  return (
    <h3 style={{
      fontFamily: mono, fontSize: F.card, color: T.text, fontWeight: 500,
      marginTop: 28, marginBottom: 8,
    }}>
      {children}
    </h3>
  )
}

export function P({ children }) {
  return <p style={{ color: T.muted, marginBottom: 16 }}>{children}</p>
}

export function UL({ items }) {
  return (
    <ul style={{ color: T.muted, paddingLeft: 24, marginBottom: 16 }}>
      {items.map((item, i) => (
        <li key={i} style={{ marginBottom: 6 }}>{item}</li>
      ))}
    </ul>
  )
}

export function Table({ headers, rows }) {
  return (
    <div style={{ overflowX: 'auto', marginBottom: 24 }}>
      <table style={{ borderCollapse: 'collapse', width: '100%', fontSize: F.legal }}>
        <thead>
          <tr>
            {headers.map(h => (
              <th key={h} style={{
                textAlign: 'left', fontFamily: mono, fontSize: F.legal,
                color: T.muted, padding: '8px 16px 8px 0',
                borderBottom: `1px solid ${T.border}`,
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
                  color: T.muted, padding: '10px 16px 10px 0',
                  borderBottom: `1px solid ${T.vdim}`, verticalAlign: 'top',
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
      style={{ color: T.amberText, textDecoration: 'none' }}
      onMouseEnter={e => e.currentTarget.style.textDecoration = 'underline'}
      onMouseLeave={e => e.currentTarget.style.textDecoration = 'none'}
    >
      {children}
    </a>
  )
}
