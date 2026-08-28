import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { docs, getDoc, CATEGORY_ORDER } from './docs'
import { T, F, S, mono, sans } from '../theme'

// Plain-text version of a page's HTML, so the search box also matches body text.
const stripHtml = html => html.replace(/<[^>]+>/g, ' ')

function matchesQuery(doc, q) {
  if (!q) return true
  const hay = `${doc.title} ${doc.excerpt} ${doc.category} ${stripHtml(doc.content)}`.toLowerCase()
  return hay.includes(q)
}

// ─── shared nav ───────────────────────────────────────────────────────────────
// Same header as the blog (src/blog/BlogPage.jsx), with `docs` lit instead of
// `blog`. If you change one, change the other: the two must not drift.
function Nav() {
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 100,
      background: `${T.bg}f2`, backdropFilter: 'blur(14px)',
      borderBottom: `1px solid ${T.vdim}`,
    }}>
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '18px 48px', maxWidth: 1200, margin: '0 auto',
      }}>
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
          {/* 40px mark + 22px wordmark, weight 500. Matches every CP header;
              see the note in LandingPage's Nav for why 40 and not FN's 34. */}
          <img src="/logo.png" alt="ClusterPilot" width={40} height={40} style={{ display: 'block' }} />
          <span style={{ fontFamily: mono, fontSize: 22, fontWeight: 500, color: T.amberText, letterSpacing: '-0.3px' }}>
            clusterpilot
          </span>
        </a>
        <div style={{ display: 'flex', gap: 28, fontSize: F.label, fontFamily: mono }}>
          <a href="/#how-it-works" style={{ color: T.muted, textDecoration: 'none' }}>how it works</a>
          <a href="/#features"     style={{ color: T.muted, textDecoration: 'none' }}>features</a>
          <a href="/#pricing"      style={{ color: T.muted, textDecoration: 'none' }}>pricing</a>
          <a href="/blog"          style={{ color: T.muted, textDecoration: 'none' }}>blog</a>
          <a href="/docs"          style={{ color: T.text,  textDecoration: 'none' }}>docs</a>
        </div>
        <a href="https://app.clusterpilot.sh" target="_blank" rel="noreferrer">
          <button style={{
            background: T.amber, color: T.ink, fontSize: F.btn, fontWeight: 700,
            padding: '8px 16px', borderRadius: 6, border: 'none', cursor: 'pointer',
            fontFamily: mono, letterSpacing: '0.3px', whiteSpace: 'nowrap',
          }}>Open app →</button>
        </a>
      </nav>
    </div>
  )
}

function Footer() {
  return (
    <footer style={{
      borderTop: `1px solid ${T.vdim}`,
      padding: '28px 48px',
      maxWidth: 1200, margin: '0 auto',
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      fontFamily: mono, fontSize: F.note, color: T.muted,
    }}>
      <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
        <img src="/logo.png" alt="" width={22} height={22} />
        <span style={{ color: T.amberText }}>clusterpilot</span>
      </a>
      <span>
        a sibling to{' '}
        <a href="https://fieldnotes.sh" target="_blank" rel="noreferrer"
          style={{ color: T.amberText, textDecoration: 'none' }}>Fieldnotes</a>
        {' '}· juliafrank.net
      </span>
    </footer>
  )
}

// ─── sidebar: search + category-grouped nav ───────────────────────────────────
function DocsSidebar({ query, setQuery, activeSlug }) {
  const q = query.trim().toLowerCase()
  const visible = docs.filter(d => matchesQuery(d, q))

  const groups = CATEGORY_ORDER
    .map(cat => ({ cat, items: visible.filter(d => d.category === cat) }))
    .filter(g => g.items.length > 0)

  // Any page whose category is not in CATEGORY_ORDER still shows, under "More".
  const known = new Set(CATEGORY_ORDER)
  const extra = visible.filter(d => !known.has(d.category))
  if (extra.length) groups.push({ cat: 'More', items: extra })

  return (
    <aside className="cp-sidebar">
      <input
        type="search"
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Search docs"
        aria-label="Search docs"
        style={{
          width: '100%', boxSizing: 'border-box', padding: '10px 14px',
          fontFamily: mono, fontSize: F.label, color: T.text,
          background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8,
          outline: 'none', marginBottom: 28,
        }}
      />

      {groups.map(g => (
        <div key={g.cat} style={{ marginBottom: 24 }}>
          <div style={{
            fontFamily: mono, fontSize: F.micro, color: T.dim,
            letterSpacing: '1.2px', textTransform: 'uppercase', marginBottom: 10,
          }}>{g.cat}</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {g.items.map(d => {
              const active = d.slug === activeSlug
              return (
                <a key={d.slug} href={`/docs/${d.slug}`}
                  className={active ? undefined : 'cp-side-link'}
                  style={{
                    display: 'block', padding: '7px 12px', borderRadius: 7,
                    fontFamily: sans, fontSize: F.label, lineHeight: 1.4,
                    textDecoration: 'none',
                    fontWeight: active ? 600 : 500,
                    color: active ? T.text : T.muted,
                    background: active ? T.panel2 : undefined,
                    borderLeft: active ? `2px solid ${T.amber}` : '2px solid transparent',
                  }}
                >{d.title}</a>
              )
            })}
          </div>
        </div>
      ))}

      {groups.length === 0 && (
        <p style={{ fontFamily: mono, fontSize: F.micro, color: T.dim }}>No matches.</p>
      )}
    </aside>
  )
}

// ─── content pane: one page ───────────────────────────────────────────────────
function DocArticle({ doc }) {
  return (
    <article>
      <div style={S.label}>
        <span style={S.labelDot} />
        <span style={S.labelText}>{doc.category}</span>
      </div>

      <h1 style={{ fontSize: 40, fontWeight: 700, letterSpacing: '-1px', margin: '0 0 36px', lineHeight: 1.15, fontFamily: sans }}>
        {doc.title}
      </h1>

      <div className="cp-prose" dangerouslySetInnerHTML={{ __html: doc.content }} />

      <div style={{ marginTop: 56, paddingTop: 32, borderTop: `1px solid ${T.vdim}` }}>
        <p style={{ fontFamily: mono, fontSize: F.note, color: T.muted, marginBottom: 16 }}>
          Install it with <code style={S.code}>pip install clusterpilot</code>, or open the web app.
        </p>
        <a href="https://app.clusterpilot.sh" target="_blank" rel="noreferrer">
          <button style={S.btnAmber}>Open app →</button>
        </a>
      </div>
    </article>
  )
}

// ─── content pane: landing (no page selected) ─────────────────────────────────
function DocsIntro() {
  return (
    <div>
      <div style={S.label}>
        <span style={S.labelDot} />
        <span style={S.labelText}>docs</span>
      </div>

      <h1 style={{ fontSize: 40, fontWeight: 700, letterSpacing: '-1px', margin: '0 0 14px', fontFamily: sans }}>
        Documentation
      </h1>
      <p style={{ fontSize: F.body, color: T.muted, margin: '0 0 36px', lineHeight: 1.7, maxWidth: 560, fontFamily: sans }}>
        Short, task-shaped guides to installing ClusterPilot, submitting jobs, and
        getting the most out of your cluster. Pick one from the list, or search.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {docs.map(doc => (
          <a key={doc.slug} href={`/docs/${doc.slug}`} style={{ textDecoration: 'none', color: 'inherit' }}>
            <div
              className="blog-list-row"
              style={{
                padding: '22px 0',
                borderBottom: `1px solid ${T.vdim}`,
                transition: 'opacity 0.15s',
              }}
            >
              <div style={{ fontFamily: mono, fontSize: F.micro, color: T.dim, marginBottom: 6, letterSpacing: '0.5px' }}>
                {doc.category}
              </div>
              <h2 style={{ fontSize: F.body, fontWeight: 600, margin: '0 0 6px', lineHeight: 1.3, fontFamily: sans }}>{doc.title}</h2>
              <p style={{ fontSize: F.item, color: T.muted, margin: 0, lineHeight: 1.65, fontFamily: sans }}>{doc.excerpt}</p>
            </div>
          </a>
        ))}
      </div>

      {docs.length === 0 && (
        <p style={{ fontSize: F.item, color: T.muted, fontFamily: mono, marginTop: 8 }}>No pages yet. Check back soon.</p>
      )}
    </div>
  )
}

// ─── router ───────────────────────────────────────────────────────────────────
export default function DocsPage() {
  const { slug } = useParams()
  const [query, setQuery] = useState('')
  const doc = slug ? getDoc(slug) : null

  let content
  if (slug && doc) {
    content = <DocArticle doc={doc} />
  } else if (slug && !doc) {
    content = (
      <div>
        <p style={{ fontFamily: mono, fontSize: F.item, color: T.muted, marginBottom: 16 }}>Page not found.</p>
        <a href="/docs" style={{ fontFamily: mono, fontSize: F.micro, color: T.amberText, textDecoration: 'none' }}>← back to docs</a>
      </div>
    )
  } else {
    content = <DocsIntro />
  }

  return (
    <div style={{ background: T.bg, color: T.text, fontFamily: sans, minHeight: '100vh' }}>
      <Nav />
      <div className="cp-side-layout">
        <DocsSidebar query={query} setQuery={setQuery} activeSlug={slug} />
        <div className="cp-side-content">{content}</div>
      </div>
      <Footer />
    </div>
  )
}
