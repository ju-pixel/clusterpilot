import { useState } from 'react'

// ─── tokens ───────────────────────────────────────────────────────────────────
const T = {
  bg:     '#000000',
  bg2:    '#0a0a0a',
  bg3:    '#111111',
  border: '#2a2a2a',
  border2:'#1a1a1a',
  amber:  '#FFB866',
  text:   '#fafafa',
  muted:  '#6b6b6b',
  dim:    '#444444',
}
const mono = "'DM Mono', 'Courier New', monospace"
const sans = "'DM Sans', system-ui, sans-serif"

const API = import.meta.env.VITE_API_URL || 'https://api.clusterpilot.sh'

// ─── nav ──────────────────────────────────────────────────────────────────────
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

// ─── input helper ─────────────────────────────────────────────────────────────
function Field({ label, id, type = 'text', value, onChange, required, rows }) {
  const base = {
    width: '100%', boxSizing: 'border-box',
    background: T.bg3, border: `1px solid ${T.border}`,
    borderRadius: 6, color: T.text,
    fontFamily: sans, fontSize: 14,
    outline: 'none',
    transition: 'border-color 0.15s',
  }
  const inputStyle = { ...base, padding: '10px 12px' }
  const textareaStyle = { ...base, padding: '10px 12px', resize: 'vertical', minHeight: 120 }
  const labelStyle = {
    display: 'block', fontFamily: mono, fontSize: 12,
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
          color: '#000', fontFamily: mono, fontSize: 13, fontWeight: 700,
          padding: '10px 24px', borderRadius: 6, border: 'none',
          cursor: status === 'sending' ? 'not-allowed' : 'pointer',
          transition: 'background 0.15s',
        }}
      >
        {status === 'sending' ? 'Sending…' : 'Send message →'}
      </button>

      {status === 'success' && (
        <p style={{ fontFamily: mono, fontSize: 13, color: '#6fcf97', marginTop: 16 }}>
          Message sent. We typically reply within one business day.
        </p>
      )}
      {status === 'error' && (
        <p style={{ fontFamily: mono, fontSize: 13, color: '#eb5757', marginTop: 16 }}>
          Something went wrong. Email us directly at{' '}
          <a href="mailto:hello@clusterpilot.sh" style={{ color: T.amber }}>hello@clusterpilot.sh</a>.
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
        <p style={{ fontFamily: mono, fontSize: 12, color: T.muted, marginBottom: 12 }}>Support</p>
        <h1 style={{ fontFamily: mono, fontSize: 32, color: T.amber, fontWeight: 500, marginBottom: 8 }}>
          Get in touch.
        </h1>
        <p style={{ color: T.muted, fontSize: 15, marginBottom: 56, maxWidth: 480 }}>
          We typically reply within one business day.
        </p>

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
            <p style={{ fontFamily: mono, fontSize: 12, color: T.muted, marginBottom: 24, letterSpacing: '0.05em' }}>
              COMMON QUESTIONS
            </p>
            {FAQ.map(({ q, a }) => (
              <div key={q} style={{
                marginBottom: 28,
                paddingBottom: 28,
                borderBottom: `1px solid ${T.border2}`,
              }}>
                <p style={{
                  fontFamily: mono, fontSize: 14, color: T.text,
                  marginBottom: 8, fontWeight: 500,
                }}>
                  {q}
                </p>
                <p style={{ fontSize: 14, color: '#aaaaaa', lineHeight: 1.65 }}>{a}</p>
              </div>
            ))}
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer style={{ borderTop: `1px solid ${T.border2}`, background: T.bg }}>
        <div style={{
          maxWidth: 1100, margin: '0 auto', padding: '28px 48px',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
        }}>
          <span style={{ fontFamily: mono, fontSize: 12, color: T.dim }}>
            Frankly Labs · Canada
          </span>
          <div style={{ display: 'flex', gap: 20 }}>
            {[['Privacy Policy', '/privacy'], ['Terms', '/terms'], ['AUP', '/acceptable-use']].map(([l, h]) => (
              <a key={l} href={h} style={{ fontFamily: mono, fontSize: 12, color: T.dim, textDecoration: 'none' }}
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
        }
      `}</style>
    </div>
  )
}
