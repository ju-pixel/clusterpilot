import { useState } from 'react'
import { T, F, mono, sans } from './theme'

const API = import.meta.env.VITE_API_URL || 'https://api.clusterpilot.sh'

// ─── nav ──────────────────────────────────────────────────────────────────────
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
          <span style={{ fontFamily: mono, fontSize: 22, fontWeight: 500, color: T.amberText, letterSpacing: '-0.3px' }}>clusterpilot</span>
        </a>
        <a href="/" style={{ fontFamily: mono, fontSize: F.label, color: T.muted, textDecoration: 'none' }}>
          ← back
        </a>
      </nav>
    </div>
  )
}

// ─── input helper ─────────────────────────────────────────────────────────────
function Field({ label, id, type = 'text', value, onChange, required, rows }) {
  const base = {
    width: '100%', boxSizing: 'border-box',
    background: T.panel2, border: `1px solid ${T.border}`,
    borderRadius: 6, color: T.text,
    fontFamily: sans, fontSize: F.btn,
    outline: 'none',
    transition: 'border-color 0.15s',
  }
  const inputStyle = { ...base, padding: '10px 12px' }
  const textareaStyle = { ...base, padding: '10px 12px', resize: 'vertical', minHeight: 120 }
  const labelStyle = {
    display: 'block', fontFamily: mono, fontSize: F.micro,
    color: T.muted, marginBottom: 6,
  }

  return (
    <div style={{ marginBottom: 20 }}>
      <label htmlFor={id} style={labelStyle}>{label}{required && ' *'}</label>
      {rows ? (
        <textarea
          id={id} name={id} rows={rows} required={required}
          value={value} onChange={onChange}
          style={textareaStyle}
          onFocus={e => e.target.style.borderColor = T.amber}
          onBlur={e => e.target.style.borderColor = T.border}
        />
      ) : (
        <input
          id={id} name={id} type={type} required={required}
          value={value} onChange={onChange}
          style={inputStyle}
          onFocus={e => e.target.style.borderColor = T.amber}
          onBlur={e => e.target.style.borderColor = T.border}
        />
      )}
    </div>
  )
}

// ─── FAQ items ────────────────────────────────────────────────────────────────
const FAQ = [
  {
    q: 'How do I cancel my subscription?',
    a: 'Open the app at app.clusterpilot.sh, go to Account, and click "Manage billing". This opens the Stripe customer portal where you can cancel at any time. Cancellation takes effect at the end of the current billing period.',
  },
  {
    q: 'Can I use ClusterPilot without a subscription?',
    a: 'Yes. ClusterPilot is open source under the MIT Licence. The self-hosted version is fully functional with your own Anthropic API key. Only the hosted proxy (managed key, no setup) requires a subscription.',
  },
  {
    q: 'Which clusters are supported?',
    a: 'Any SLURM cluster. ClusterPilot ships with optimised profiles for Compute Canada / DRAC (Cedar, Narval, Graham, Beluga) and University of Manitoba Grex. Generic SLURM support covers any other cluster.',
  },
  {
    q: 'Where does my job code go?',
    a: 'When using the hosted tier, your job description and code are sent to the AI model to generate the SLURM script, then discarded. They are not stored on our servers. See the Privacy Policy for details.',
  },
  {
    q: 'I need a seat bundle for my research group.',
    a: 'PI group plans are available at checkout — click "Buying for your group?" in the subscribe flow. You will receive invite codes to distribute to each researcher in your team.',
  },
]

// ─── contact form ─────────────────────────────────────────────────────────────
function ContactForm() {
  const [form, setForm] = useState({ name: '', email: '', message: '' })
  const [status, setStatus] = useState('idle') // idle | sending | success | error

  const set = field => e => setForm(f => ({ ...f, [field]: e.target.value }))

  const submit = async e => {
    e.preventDefault()
    setStatus('sending')
    try {
      const r = await fetch(`${API}/email/contact`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      })
      if (!r.ok) throw new Error('non-200')
      setStatus('success')
      setForm({ name: '', email: '', message: '' })
    } catch {
      setStatus('error')
    }
  }

  return (
    <form onSubmit={submit}>
      <Field label="Your name" id="name" value={form.name} onChange={set('name')} required />
      <Field label="Email address" id="email" type="email" value={form.email} onChange={set('email')} required />
      <Field label="Message" id="message" value={form.message} onChange={set('message')} required rows={5} />

      <button
        type="submit"
        disabled={status === 'sending'}
        style={{
          background: status === 'sending' ? T.dim : T.amber,
          color: T.ink, fontFamily: mono, fontSize: F.btn, fontWeight: 700,
          padding: '10px 24px', borderRadius: 6, border: 'none',
          cursor: status === 'sending' ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}
      >
        {status === 'sending' ? 'Sending…' : 'Send message →'}
      </button>

      {status === 'success' && (
        <p style={{ fontFamily: mono, fontSize: F.item, color: T.green, marginTop: 16 }}>
          Message sent. We typically reply within one business day.
        </p>
      )}
      {status === 'error' && (
        <p style={{ fontFamily: mono, fontSize: F.item, color: T.red, marginTop: 16 }}>
          Something went wrong. Email us directly at{' '}
          <a href="mailto:hello@clusterpilot.sh" style={{ color: T.amberText }}>hello@clusterpilot.sh</a>.
        </p>
      )}
    </form>
  )
}

// ─── page ─────────────────────────────────────────────────────────────────────
export default function Support() {
  return (
    <div style={{ background: T.bg, color: T.text, minHeight: '100vh', fontFamily: sans }}>
      <Nav />
      <main style={{ maxWidth: 1100, margin: '0 auto', padding: '64px 48px 100px' }}>

        {/* Header */}
        <p style={{ fontFamily: mono, fontSize: F.micro, color: T.muted, marginBottom: 12 }}>Support</p>
        {/* 32 mono, unchanged: the B.2 "H1 clamp 58/32" is the landing hero's
            size. A 58px mono headline would shout, and 32 was never the
            readability problem here; the 12-14px body copy was. */}
        <h1 style={{ fontFamily: mono, fontSize: 32, color: T.amberText, fontWeight: 500, marginBottom: 8 }}>
          Get in touch.
        </h1>
        <p style={{ color: T.muted, fontSize: F.body, marginBottom: 32, maxWidth: 480 }}>
          We typically reply within one business day.
        </p>

        {/* Feature requests → Featurebase board */}
        <div
          className="support-roadmap-card"
          style={{
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            background: T.panel,
            padding: '24px 28px',
            marginBottom: 56,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 24,
            flexWrap: 'wrap',
          }}
        >
          <div style={{ maxWidth: 560 }}>
            <p style={{
              fontFamily: mono, fontSize: F.micro, color: T.amberText,
              marginBottom: 8, letterSpacing: '0.05em',
            }}>
              ROADMAP
            </p>
            <p style={{
              fontFamily: mono, fontSize: F.card, color: T.text,
              marginBottom: 6, fontWeight: 500,
            }}>
              Want a feature, not a fix?
            </p>
            <p style={{ fontSize: F.item, color: T.muted, lineHeight: 1.55, margin: 0 }}>
              Vote on roadmap items or post a new request at{' '}
              <a
                href="https://clusterpilot.featurebase.app"
                target="_blank"
                rel="noreferrer"
                style={{ color: T.amberText, textDecoration: 'none' }}
              >
                clusterpilot.featurebase.app
              </a>
              . The form below is for bugs, billing, and account questions.
            </p>
          </div>
          <a
            href="https://clusterpilot.featurebase.app"
            target="_blank"
            rel="noreferrer"
            style={{ textDecoration: 'none', flexShrink: 0 }}
          >
            <button style={{
              background: T.amber, color: T.ink, fontSize: F.btn, fontWeight: 700,
              padding: '10px 20px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontFamily: mono, whiteSpace: 'nowrap',
            }}>
              Open the roadmap →
            </button>
          </a>
        </div>

        {/* Two-column layout */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)',
          gap: 64,
          alignItems: 'start',
        }}
          className="support-grid"
        >
          {/* Left: contact form */}
          <div>
            <ContactForm />
          </div>

          {/* Right: FAQ */}
          <div>
            <p style={{ fontFamily: mono, fontSize: F.micro, color: T.muted, marginBottom: 24, letterSpacing: '0.05em' }}>
              COMMON QUESTIONS
            </p>
            {FAQ.map(({ q, a }) => (
              <div key={q} style={{
                marginBottom: 28,
                paddingBottom: 28,
                borderBottom: `1px solid ${T.vdim}`,
              }}>
                <p style={{
                  fontFamily: mono, fontSize: F.card, color: T.text,
                  marginBottom: 8, fontWeight: 500,
                }}>
                  {q}
                </p>
                <p style={{ fontSize: F.item, color: T.muted, lineHeight: 1.65 }}>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer style={{ borderTop: `1px solid ${T.vdim}`, background: T.bg }}>
        <div style={{
          maxWidth: 1100, margin: '0 auto', padding: '28px 48px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
        }}>
          <span style={{ fontFamily: mono, fontSize: F.note, color: T.dim }}>
            Frankly Labs · Canada
          </span>
          <div style={{ display: 'flex', gap: 20 }}>
            {[['Privacy Policy', '/privacy'], ['Terms', '/terms'], ['AUP', '/acceptable-use']].map(([l, h]) => (
              <a key={l} href={h} style={{ fontFamily: mono, fontSize: F.note, color: T.dim, textDecoration: 'none' }}
                onMouseEnter={e => e.currentTarget.style.color = T.muted}
                onMouseLeave={e => e.currentTarget.style.color = T.dim}
              >{l}</a>
            ))}
          </div>
        </div>
      </footer>

      <style>{`
        @media (max-width: 680px) {
          .support-grid { grid-template-columns: 1fr !important; gap: 48px !important; }
          .support-roadmap-card { flex-direction: column; align-items: stretch !important; }
          .support-roadmap-card button { width: 100%; }
        }
      `}</style>
    </div>
  )
}
