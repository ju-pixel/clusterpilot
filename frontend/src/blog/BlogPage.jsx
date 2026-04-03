import { useParams } from 'react-router-dom'
import { posts, getPost } from './posts'

// ─── tokens ───────────────────────────────────────────────────────────────────
const T = {
  bg: '#000', panel: '#0d0d0d',
  border: '#2a2a2a', border2: '#1a1a1a',
  amber: '#FFB866',
  text: '#fafafa', muted: '#6b6b6b', dim: '#444',
}
const mono = "'DM Mono', 'Courier New', monospace"
const sans = "'DM Sans', system-ui, sans-serif"

// ─── shared nav ───────────────────────────────────────────────────────────────
function Nav() {
  return (
    <div style={{
      position: 'sticky', top: 0, zIndex: 100,
      background: `${T.bg}f2`, backdropFilter: 'blur(14px)',
      borderBottom: `1px solid ${T.border2}`,
    }}>
      <nav style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '18px 48px', maxWidth: 1200, margin: '0 auto',
      }}>
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
          <img src="/logo.png" alt="ClusterPilot" width={30} height={30} style={{ display: 'block' }} />
          <span style={{ fontFamily: mono, fontSize: 18, color: T.amber, letterSpacing: '-0.3px' }}>
            clusterpilot
          </span>
        </a>
        <div style={{ display: 'flex', gap: 28, fontSize: 14, fontFamily: mono }}>
          <a href="/#how-it-works" style={{ color: T.muted, textDecoration: 'none' }}>how it works</a>
          <a href="/#features"     style={{ color: T.muted, textDecoration: 'none' }}>features</a>
          <a href="/#pricing"      style={{ color: T.muted, textDecoration: 'none' }}>pricing</a>
          <a href="/blog"          style={{ color: T.text,  textDecoration: 'none' }}>blog</a>
        </div>
        <a href="https://app.clusterpilot.sh" target="_blank" rel="noreferrer">
          <button style={{
            background: T.amber, color: '#000', fontSize: 13, fontWeight: 700,
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
      borderTop: `1px solid ${T.border2}`,
      padding: '28px 48px',
      maxWidth: 1200, margin: '0 auto',
      display: 'flex', justifyContent: 'space-between', alignItems: 'center',
      fontFamily: mono, fontSize: 13, color: T.muted,
    }}>
      <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
        <img src="/logo.png" alt="" width={22} height={22} />
        <span style={{ color: T.amber }}>clusterpilot</span>
      </a>
      <span>
        a sibling to{' '}
        <a href="https://fieldnotes.sh" target="_blank" rel="noreferrer"
          style={{ color: T.amber, textDecoration: 'none' }}>Fieldnotes</a>
        {' '}· juliafrank.net
      </span>
    </footer>
  )
}

// ─── blog list ────────────────────────────────────────────────────────────────
function BlogList() {
  return (
    <main style={{ maxWidth: 1200, margin: '0 auto', padding: '80px 48px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: T.amber, display: 'inline-block', flexShrink: 0 }} />
        <span style={{ fontFamily: mono, fontSize: 12, color: T.muted, letterSpacing: '1.5px', textTransform: 'uppercase' }}>blog</span>
      </div>
      <h1 style={{ fontSize: 36, fontWeight: 700, letterSpacing: '-1px', margin: '0 0 12px', fontFamily: sans }}>
        Articles on HPC and cluster workflows
      </h1>
      <p style={{ fontSize: 17, color: T.muted, margin: '0 0 52px', lineHeight: 1.7, maxWidth: 560, fontFamily: sans }}>
        Practical guides, SLURM gotchas, and notes on building tools for computational researchers.
      </p>

      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {posts.map(post => (
          <a key={post.slug} href={`/blog/${post.slug}`} style={{ textDecoration: 'none', color: 'inherit' }}>
            <div
              style={{
                padding: '28px 0',
                borderBottom: `1px solid ${T.border2}`,
                display: 'flex', gap: 40, alignItems: 'flex-start',
                transition: 'opacity 0.15s',
              }}
              onMouseEnter={e => e.currentTarget.style.opacity = '0.7'}
              onMouseLeave={e => e.currentTarget.style.opacity = '1'}
            >
              <span style={{ fontFamily: mono, fontSize: 13, color: T.dim, flexShrink: 0, marginTop: 4, minWidth: 90 }}>
                {formatDate(post.date)}
              </span>
              <div>
                <h2 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 8px', lineHeight: 1.3, fontFamily: sans }}>{post.title}</h2>
                <p style={{ fontSize: 15, color: T.muted, margin: 0, lineHeight: 1.65, fontFamily: sans }}>{post.excerpt}</p>
              </div>
            </div>
          </a>
        ))}
      </div>

      {posts.length === 0 && (
        <p style={{ fontSize: 15, color: T.muted, fontFamily: mono, marginTop: 8 }}>No posts yet. Check back soon.</p>
      )}
    </main>
  )
}

// ─── single post ──────────────────────────────────────────────────────────────
function BlogPost({ post }) {
  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '64px 40px' }}>
      <a href="/blog" style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        fontFamily: mono, fontSize: 13, color: T.muted, textDecoration: 'none',
        marginBottom: 40,
      }}>
        ← all posts
      </a>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ width: 5, height: 5, borderRadius: '50%', background: T.amber, display: 'inline-block', flexShrink: 0 }} />
        <span style={{ fontFamily: mono, fontSize: 13, color: T.muted, letterSpacing: '1.5px', textTransform: 'uppercase' }}>
          {formatDate(post.date)}
        </span>
      </div>

      <h1 style={{ fontSize: 36, fontWeight: 700, letterSpacing: '-1px', margin: '0 0 40px', lineHeight: 1.15, fontFamily: sans }}>
        {post.title}
      </h1>

      <div className="cp-prose" dangerouslySetInnerHTML={{ __html: post.content }} />

      <div style={{ marginTop: 64, paddingTop: 32, borderTop: `1px solid ${T.border2}` }}>
        <p style={{ fontFamily: mono, fontSize: 13, color: T.muted, marginBottom: 16 }}>
          Try ClusterPilot for free — no account required.
        </p>
        <a href="https://github.com/ju-pixel/clusterpilot" target="_blank" rel="noreferrer">
          <button style={{
            background: T.amber, color: '#000', fontSize: 15, fontWeight: 700,
            padding: '11px 22px', borderRadius: 7, border: 'none', cursor: 'pointer',
            fontFamily: mono, letterSpacing: '0.3px',
          }}>View on GitHub →</button>
        </a>
      </div>
    </main>
  )
}

// ─── helpers ──────────────────────────────────────────────────────────────────
function formatDate(iso) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ─── router ───────────────────────────────────────────────────────────────────
export default function BlogPage() {
  const { slug } = useParams()
  if (slug) {
    const post = getPost(slug)
    if (!post) {
      return (
        <div style={{ background: T.bg, color: T.text, fontFamily: sans, minHeight: '100vh' }}>
          <Nav />
          <main style={{ maxWidth: 1200, margin: '0 auto', padding: '80px 48px' }}>
            <p style={{ fontFamily: mono, fontSize: 15, color: T.muted }}>Post not found.</p>
            <a href="/blog" style={{ fontFamily: mono, fontSize: 14, color: T.muted }}>← back to blog</a>
          </main>
          <Footer />
        </div>
      )
    }
    return (
      <div style={{ background: T.bg, color: T.text, fontFamily: sans, minHeight: '100vh' }}>
        <Nav />
        <BlogPost post={post} />
        <Footer />
      </div>
    )
  }
  return (
    <div style={{ background: T.bg, color: T.text, fontFamily: sans, minHeight: '100vh' }}>
      <Nav />
      <BlogList />
      <Footer />
    </div>
  )
}
