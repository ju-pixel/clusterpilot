import { useState } from 'react'

// ─── tokens ───────────────────────────────────────────────────────────────────
const T = {
  bg:      '#000000',
  bg2:     '#0a0a0a',
  bg3:     '#111111',
  border:  '#2a2a2a',
  border2: '#1a1a1a',
  amber:   '#FFB866',
  text:    '#fafafa',
  muted:   '#6b6b6b',
  dim:     '#444444',
}
const mono  = "'DM Mono', 'Courier New', monospace"
const sans  = "'DM Sans', system-ui, sans-serif"
const serif = "'Playfair Display', Georgia, serif"

// ─── page data ────────────────────────────────────────────────────────────────
const STEPS = [
  {
    n: '01', title: 'Choose a cluster',
    body: 'Add as many clusters as you have access to – each gets its own profile in the config file. Select your target cluster. Partition options, GPU flags, account names, and scratch paths load automatically.',
  },
  {
    n: '02', title: 'Pick your job type',
    body: 'Point to a self-contained script (Julia, Python, or other), or a full package with a driver script. ClusterPilot reads your Project.toml and Manifest.toml to wire up the environment.',
  },
  {
    n: '03', title: 'Describe your job',
    body: 'Type what your job does in plain English. The script is generated from both your description and the actual code – cluster constraints, environment setup, and all.',
  },
  {
    n: '04', title: 'Review and submit',
    body: 'A complete SLURM script appears. Edit inline if needed, then upload and submit in one keypress over your existing SSH ControlMaster socket.',
  },
  {
    n: '05', title: 'Monitor passively',
    body: 'A background daemon polls squeue at a configurable interval (default 5 minutes). Get push notifications on your phone when jobs start, finish, or fail.',
  },
  {
    n: '06', title: 'Results synced back',
    body: 'On completion, output files are rsynced to your local project directory. Source code is skipped. Only results come back.',
  },
]

const FEATURES = [
  {
    n: '01', title: 'Code-aware script generation',
    body: 'The SLURM script is generated from both your plain-English description and the actual job code – cluster constraints, GPU flags, and environment setup included. For Julia packages, it reads your Project.toml and writes the correct Pkg.instantiate() calls. For self-contained scripts, it infers dependencies and handles module loading automatically.',
  },
  {
    n: '02', title: 'One-keypress submit',
    body: 'Files are rsynced and sbatch runs over your existing SSH ControlMaster socket. No new SSH sessions, no changes to ~/.ssh/config.',
  },
  {
    n: '03', title: 'Passive monitoring',
    body: 'Two modes depending on how you work. Keep the TUI open and the job list refreshes every 10 seconds – tail logs live, check status at a glance. Or close the lid entirely: the background daemon polls squeue every 5 minutes, notifies you on job start, completion, and failure, and syncs results when done.',
  },
  {
    n: '04', title: 'Push notifications',
    body: 'Optional ntfy.sh integration sends job start, completion, failure, and walltime warnings straight to your phone. No account required.',
  },
  {
    n: '05', title: 'Sync results + cluster cleanup',
    body: 'On completion, output files sync back to your local project directory. Source is skipped. Your data is already there when you open the lid. Optionally clean up the job directory on the cluster to reclaim scratch space without SSH-ing in manually.',
  },
  {
    n: '06', title: 'Job arrays',
    body: 'Submit parametric sweeps as SLURM job arrays directly from the submission UI. Just tell the AI what you want – "run this over L = 4, 6, 8, 10" – and it generates the correct #SBATCH --array directive, maps the index to your parameter, and handles the rest.',
  },
]

const AUDIENCE = [
  {
    n: '01', title: 'Computational researchers running GPU simulations',
    sub: 'Monte Carlo, MD, DFT, ML training – if it runs on a V100, it fits.',
  },
  {
    n: '02', title: 'Students new to HPC clusters',
    sub: 'Stop copying SLURM scripts from Stack Overflow and hoping they work.',
  },
  {
    n: '03', title: 'Anyone submitting multiple jobs a day',
    sub: 'Each submission gets its own isolated directory. No more overwriting results.',
  },
  {
    n: '04', title: 'Researchers tired of cluster-specific gotchas',
    sub: 'GPU syntax, account flags, scratch paths, module names – all handled automatically. You describe the job, ClusterPilot handles the rest.',
  },
]

// ─── nav ──────────────────────────────────────────────────────────────────────
function Nav() {
  const [menuOpen, setMenuOpen] = useState(false)

  const linkStyle = { color: '#aaaaaa', textDecoration: 'none', fontFamily: mono, fontSize: 15 }
  const mobileLink = {
    ...linkStyle,
    display: 'block',
    padding: '10px 0',
    borderBottom: `1px solid ${T.border2}`,
    fontSize: 16,
  }

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
        {/* Logo */}
        <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
          <img src="/logo.png" alt="ClusterPilot" width={32} height={32} style={{ display: 'block' }} />
          <span style={{ fontFamily: mono, fontSize: 19, color: T.amber, letterSpacing: '-0.3px' }}>
            clusterpilot
          </span>
        </a>

        {/* Desktop links */}
        <div className="nav-links" style={{ gap: 28, alignItems: 'center' }}>
          <a href="#how-it-works" style={linkStyle}>How it works</a>
          <a href="#features"     style={linkStyle}>Features</a>
          <a href="#pricing"      style={linkStyle}>Pricing</a>
          <a href="https://github.com/ju-pixel/clusterpilot" target="_blank" rel="noreferrer" style={linkStyle}>GitHub</a>
          <a href="/blog"         style={linkStyle}>Blog</a>
          <a href="/support"      style={linkStyle}>Support</a>
        </div>

        {/* Desktop CTA */}
        <div className="nav-cta">
          <a href="https://app.clusterpilot.sh" target="_blank" rel="noreferrer">
            <button style={{
              background: T.amber, color: '#000', fontSize: 13, fontWeight: 700,
              padding: '9px 18px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontFamily: mono, letterSpacing: '0.3px', whiteSpace: 'nowrap',
            }}>Open app →</button>
          </a>
        </div>

        {/* Hamburger */}
        <button
          className="nav-hamburger"
          onClick={() => setMenuOpen(o => !o)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: T.text, fontFamily: mono, fontSize: 20, lineHeight: 1,
            padding: 4,
          }}
          aria-label="Toggle menu"
        >
          {menuOpen ? '✕' : '☰'}
        </button>
      </nav>

      {/* Mobile dropdown */}
      <div className={`mobile-menu${menuOpen ? ' open' : ''}`}>
        <a href="#how-it-works" onClick={() => setMenuOpen(false)} style={mobileLink}>How it works</a>
        <a href="#features"     onClick={() => setMenuOpen(false)} style={mobileLink}>Features</a>
        <a href="#pricing"      onClick={() => setMenuOpen(false)} style={mobileLink}>Pricing</a>
        <a href="https://github.com/ju-pixel/clusterpilot" target="_blank" rel="noreferrer" style={mobileLink}>GitHub</a>
        <a href="/blog"         onClick={() => setMenuOpen(false)} style={mobileLink}>Blog</a>
        <a href="/support"      onClick={() => setMenuOpen(false)} style={mobileLink}>Support</a>
        <div style={{ paddingTop: 12 }}>
          <a href="https://app.clusterpilot.sh" target="_blank" rel="noreferrer">
            <button style={{
              background: T.amber, color: '#000', fontSize: 14, fontWeight: 700,
              padding: '10px 20px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontFamily: mono, width: '100%',
            }}>Open app →</button>
          </a>
        </div>
      </div>
    </div>
  )
}

// ─── pip install block ────────────────────────────────────────────────────────
function PipBlock() {
  const [copied, setCopied] = useState(false)
  const [hovered, setHovered] = useState(false)

  function handleCopy() {
    navigator.clipboard.writeText('pip install clusterpilot')
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div
      onClick={handleCopy}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 10,
        background: '#111', border: `1px solid ${hovered ? T.amber : T.border}`,
        borderRadius: 6, padding: '10px 16px', cursor: 'pointer',
        fontFamily: mono, fontSize: 14,
        transition: 'border-color 0.2s',
        marginBottom: 28,
      }}
    >
      <span style={{ color: T.muted }}>$</span>
      <span style={{ color: T.text }}>pip install clusterpilot</span>
      <span style={{ color: hovered ? T.amber : T.muted, fontSize: 12, transition: 'color 0.2s' }}>
        {copied ? 'copied!' : 'copy'}
      </span>
    </div>
  )
}

// ─── TUI mock ─────────────────────────────────────────────────────────────────
function TuiMock() {
  const amber  = T.amber
  const bg     = '#0c0a06'
  const bg2    = '#111008'
  const border = '#2a2415'
  const white  = '#f0e8d0'
  const dim    = '#7a6a50'
  const green  = '#6ed86e'
  const blue   = '#60a8d0'
  const mono2  = "'JetBrains Mono', 'Fira Code', 'DM Mono', monospace"

  const scriptLines = [
    ['shebang', '#!/bin/bash'],
    ['sbatch',  '#SBATCH --job-name=autocorr_ising_l6'],
    ['sbatch',  '#SBATCH --account=def-stamps'],
    ['sbatch',  '#SBATCH --partition=stamps'],
    ['sbatch',  '#SBATCH --nodes=1'],
    ['sbatch',  '#SBATCH --ntasks-per-node=1'],
    ['sbatch',  '#SBATCH --cpus-per-task=4'],
    ['sbatch',  '#SBATCH --mem=32G'],
    ['sbatch',  '#SBATCH --time=0-00:30:00'],
    ['sbatch',  '#SBATCH --gres=gpu:v100:1'],
    ['sbatch',  '#SBATCH --output=%x-%j.out'],
    ['blank',   ''],
    ['module',  'module purge'],
    ['module',  'module load julia/1.11.3'],
    ['blank',   ''],
    ['cmd',     'cd $SLURM_SUBMIT_DIR'],
    ['blank',   ''],
    ['cmd',     'julia --project=. -e \'import Pkg; Pkg.instantiate()\''],
    ['cmd',     'julia --project=. scripts/run_autocorrelation.jl \\'],
    ['arg',     '    --model ising --bimodal --N 216 --S 30 \\'],
    ['arg',     '    --ladder data/feedback_ladder.jld2'],
  ]

  return (
    <div style={{
      background: bg, border: `1px solid ${border}`, borderRadius: 8,
      overflow: 'hidden', fontFamily: mono2, fontSize: 13,
      boxShadow: '0 24px 64px rgba(0,0,0,0.6)',
    }}>
      {/* Title bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '8px 12px',
        background: '#0a0805', borderBottom: `1px solid ${border}`,
      }}>
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#e05050' }} />
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#c8a020' }} />
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#4a8a4a' }} />
        <span style={{ marginLeft: 8, color: dim, fontSize: 13 }}>clusterpilot</span>
      </div>

      {/* Top bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '4px 10px', background: bg2, borderBottom: `1px solid ${border}`,
        fontSize: 12,
      }}>
        <span style={{ color: amber, fontWeight: 600 }}>◆ CLUSTERPILOT</span>
        <span style={{ marginLeft: 'auto', color: dim }}>API spend: </span>
        <span style={{ color: amber }}>$0.0042</span>
        <div style={{ display: 'flex', gap: 2, marginLeft: 8 }}>
          {['F1 JOBS', 'F2 SUBMIT', 'F9 CONFIG'].map((t, i) => (
            <span key={t} style={{
              padding: '2px 8px',
              background: i === 1 ? amber : 'transparent',
              color: i === 1 ? bg : dim,
              borderRadius: 2, fontSize: 12,
            }}>{t}</span>
          ))}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <div style={{ width: 6, height: 6, borderRadius: '50%', background: green }} />
          <span style={{ color: dim }}>grex</span>
        </div>
      </div>

      {/* Main panels */}
      <div style={{ display: 'flex', height: 420 }}>
        {/* Left: form + hints */}
        <div style={{
          flex: '0 0 42%', padding: '12px', borderRight: `1px solid ${border}`,
          display: 'flex', flexDirection: 'column', gap: 7, overflow: 'hidden',
        }}>
          <div style={{ fontSize: 13, color: dim, letterSpacing: '0.1em' }}>DESCRIBE YOUR JOB</div>

          <div>
            <div style={{ fontSize: 13, color: dim, marginBottom: 3 }}>PARTITION</div>
            <div style={{
              background: bg2, border: `1px solid ${border}`,
              padding: '4px 8px', borderRadius: 3, color: amber, fontSize: 12,
            }}>stamps &nbsp;<span style={{ color: dim }}>▾</span></div>
          </div>

          <div>
            <div style={{ fontSize: 13, color: dim, marginBottom: 3 }}>PROJECT DIR</div>
            <div style={{
              background: bg2, border: `1px solid ${border}`,
              padding: '4px 8px', borderRadius: 3, color: white, fontSize: 12,
            }}>SpinGlassLab/</div>
          </div>

          <div>
            <div style={{ fontSize: 13, color: dim, marginBottom: 3 }}>DRIVER SCRIPT</div>
            <div style={{
              background: bg2, border: `1px solid ${amber}`,
              padding: '4px 8px', borderRadius: 3, color: white, fontSize: 12,
            }}>scripts/run_autocorrelation.jl</div>
          </div>

          <div style={{ flex: 1, minHeight: 0 }}>
            <div style={{ fontSize: 13, color: dim, marginBottom: 3 }}>DESCRIBE YOUR JOB</div>
            <div style={{
              background: bg2, border: `1px solid ${border}`,
              padding: '6px 8px', borderRadius: 3, color: dim, fontSize: 12,
              lineHeight: 1.5, height: '100%', overflow: 'hidden',
            }}>
              Calculates autocorrelation for N=216 Ising spins on a 3D cubic
              lattice. A few minutes per run.
            </div>
          </div>

          {/* Contextual hint panel (shown when DRIVER SCRIPT field is focused) */}
          <div style={{
            background: '#0d1a10', border: `1px solid #1a3a20`,
            borderRadius: 3, padding: '7px 9px', fontSize: 13,
          }}>
            <div style={{ color: green, marginBottom: 4, letterSpacing: '0.08em' }}>▸ HINT — DRIVER SCRIPT</div>
            <div style={{ color: '#5a8a60', lineHeight: 1.5 }}>
              Path relative to project root.<br />
              For Julia packages, Project.toml and<br />
              Manifest.toml are read automatically<br />
              to wire up Pkg.instantiate().
            </div>
          </div>

          <div style={{
            background: amber, color: bg, padding: '5px 0',
            textAlign: 'center', borderRadius: 3, fontSize: 12, fontWeight: 600,
            cursor: 'pointer', flexShrink: 0,
          }}>◎  GENERATE SCRIPT</div>
        </div>

        {/* Right: script output */}
        <div style={{ flex: 1, padding: '12px', display: 'flex', flexDirection: 'column', gap: 6, overflow: 'hidden' }}>
          <div style={{ fontSize: 13, color: dim, letterSpacing: '0.1em' }}>GENERATED SLURM SCRIPT</div>
          <div style={{ flex: 1, overflow: 'hidden', fontSize: 12, lineHeight: 1.65 }}>
            {scriptLines.map(([type, line], i) => (
              <div key={i} style={{
                color: type === 'shebang' ? dim
                     : type === 'sbatch'  ? blue
                     : type === 'module'  ? '#a0d0a0'
                     : type === 'arg'     ? '#a08050'
                     : type === 'blank'   ? 'transparent'
                     : white,
                whiteSpace: 'pre',
              }}>{line || '\u00a0'}</div>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
            {['⚡ UPLOAD + SUBMIT', '✎ EDIT', '↓ SAVE', '✕ CLEAR'].map((label, i) => (
              <div key={label} style={{
                background: i === 0 ? amber : bg2,
                color: i === 0 ? bg : dim,
                border: `1px solid ${i === 0 ? amber : border}`,
                padding: '3px 8px', borderRadius: 3, fontSize: 13, cursor: 'pointer', whiteSpace: 'nowrap',
              }}>{label}</div>
            ))}
          </div>
        </div>
      </div>

      {/* Status bar */}
      <div style={{
        display: 'flex', gap: 16, padding: '4px 10px',
        background: bg2, borderTop: `1px solid ${border}`, fontSize: 13,
      }}>
        {[['F1', 'JOBS'], ['F2', 'SUBMIT'], ['F3', 'FILES'], ['F9', 'CONFIG'], ['Q', 'QUIT']].map(([k, l]) => (
          <span key={k} style={{ color: dim }}>
            <span style={{ color: amber }}>{k}</span> {l}
          </span>
        ))}
      </div>
    </div>
  )
}

// ─── hero ─────────────────────────────────────────────────────────────────────
function Hero() {
  return (
    <section style={{ background: T.bg, borderBottom: `1px solid ${T.border2}` }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '88px 48px 80px' }}>
        <h1 style={{
          fontFamily: sans, fontWeight: 700, lineHeight: 1.05,
          fontSize: 'clamp(36px, 4vw, 62px)',
          margin: '0 0 4px',
        }}>
          Stop writing SLURM scripts
        </h1>
        <h1 style={{
          fontFamily: serif, fontStyle: 'italic', fontWeight: 700,
          fontSize: 'clamp(36px, 4vw, 62px)',
          color: T.amber, margin: '0 0 28px', lineHeight: 1.05,
        }}>
          by hand.
        </h1>

        <p style={{
          fontSize: 20, color: T.muted, lineHeight: 1.7, maxWidth: 580,
          marginBottom: 32, fontFamily: sans,
        }}>
          ClusterPilot is a keyboard-driven TUI that turns a plain-English job description into a correct,
          code and cluster-aware SLURM script – then uploads, submits, monitors, and syncs results back.
          Supports Compute Canada, university clusters, NSF ACCESS, ARCHER2, EuroHPC, and any standard
          SLURM environment.{' '}
          <strong style={{ color: T.text }}>Built by a PhD student who got tired of doing this manually.</strong>
        </p>

        <PipBlock />

        {/* CTA buttons */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
          <a href="https://github.com/ju-pixel/clusterpilot" target="_blank" rel="noreferrer">
            <button style={{
              background: T.amber, color: '#000', fontFamily: mono, fontWeight: 700,
              fontSize: 14, padding: '11px 22px', borderRadius: 6, border: 'none', cursor: 'pointer',
            }}>View on GitHub →</button>
          </a>
          <a href="https://pypi.org/project/clusterpilot/" target="_blank" rel="noreferrer">
            <button style={{
              background: 'transparent', color: T.muted, fontFamily: mono,
              fontSize: 14, padding: '10px 20px', borderRadius: 6,
              border: `1px solid ${T.border}`, cursor: 'pointer',
            }}>PyPI page</button>
          </a>
          <a href="https://youtu.be/Bw8MUUtNOss" target="_blank" rel="noreferrer">
            <button style={{
              background: 'transparent', color: T.muted, fontFamily: mono,
              fontSize: 14, padding: '10px 20px', borderRadius: 6,
              border: `1px solid ${T.border}`, cursor: 'pointer',
            }}>Watch demo ▶</button>
          </a>
        </div>
      </div>
    </section>
  )
}

// ─── TUI showcase (full-width, below hero) ────────────────────────────────────
function TuiShowcase() {
  return (
    <section style={{ background: T.bg2, borderBottom: `1px solid ${T.border2}` }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '56px 48px' }}>
        <TuiMock />
      </div>
    </section>
  )
}

// ─── how it works ─────────────────────────────────────────────────────────────
function HowItWorks() {
  return (
    <section id="how-it-works" style={{
      background: T.bg, borderBottom: `1px solid ${T.border2}`,
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '80px 48px' }}>
        {/* Section heading */}
        <div style={{ marginBottom: 52 }}>
          <p style={{ fontFamily: mono, fontSize: 12, color: T.amber, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: 12 }}>
            How it works
          </p>
          <h2 style={{ fontFamily: sans, fontWeight: 700, fontSize: 36, margin: '0 0 4px', color: T.text }}>
            Six steps.
          </h2>
          <h2 style={{ fontFamily: serif, fontStyle: 'italic', fontWeight: 700, fontSize: 36, color: T.amber, margin: 0 }}>
            Zero SSH copy-paste.
          </h2>
        </div>

        {/* Connector line + steps */}
        <div style={{ position: 'relative' }}>
          <div style={{
            position: 'absolute', top: 20, left: 0, right: 0, height: 1,
            background: `linear-gradient(to right, ${T.amber}, transparent)`,
            pointerEvents: 'none',
          }} />
          <div className="steps-grid">
            {STEPS.map(step => (
              <div key={step.n} style={{ padding: '0 24px 0 0' }}>
                <div style={{
                  width: 40, height: 40, borderRadius: '50%',
                  border: `1px solid ${T.amber}`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontFamily: mono, fontSize: 12, color: T.amber,
                  marginBottom: 20, background: T.bg, position: 'relative', zIndex: 1,
                }}>
                  {step.n}
                </div>
                <h3 style={{ fontFamily: sans, fontWeight: 700, fontSize: 17, color: T.text, marginBottom: 10 }}>
                  {step.title}
                </h3>
                <p style={{ fontFamily: sans, fontSize: 15, color: T.muted, lineHeight: 1.6 }}>
                  {step.body}
                </p>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── features ─────────────────────────────────────────────────────────────────
function FeatureCell({ n, title, body }) {
  return (
    <div className="feature-cell">
      <div className="feature-cell-bar" />
      <p style={{ fontFamily: mono, fontSize: 13, color: T.amber, marginBottom: 14, letterSpacing: '0.05em' }}>
        {n} –
      </p>
      <h3 style={{ fontFamily: sans, fontWeight: 700, fontSize: 17, color: T.text, marginBottom: 12 }}>
        {title}
      </h3>
      <p style={{ fontFamily: sans, fontSize: 16, color: T.muted, lineHeight: 1.65 }}>
        {body}
      </p>
    </div>
  )
}

function Features() {
  const row1 = FEATURES.slice(0, 3)
  const row2 = FEATURES.slice(3, 6)
  return (
    <section id="features" style={{
      background: T.bg, borderBottom: `1px solid ${T.border2}`,
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '80px 48px' }}>
        <div style={{ marginBottom: 52 }}>
          <p style={{ fontFamily: mono, fontSize: 12, color: T.amber, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: 12 }}>
            Features
          </p>
          <h2 style={{ fontFamily: sans, fontWeight: 700, fontSize: 36, margin: '0 0 4px', color: T.text }}>
            Everything in the loop.
          </h2>
          <h2 style={{ fontFamily: serif, fontStyle: 'italic', fontWeight: 700, fontSize: 36, color: T.amber, margin: 0 }}>
            Nothing you didn't ask for.
          </h2>
        </div>

        <div style={{ border: `1px solid ${T.border}`, borderRadius: 8, overflow: 'hidden' }}>
          <div className="features-row" style={{ borderBottom: `1px solid ${T.border}` }}>
            {row1.map(f => <FeatureCell key={f.n} {...f} />)}
          </div>
          <div className="features-row">
            {row2.map(f => <FeatureCell key={f.n} {...f} />)}
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── audience ─────────────────────────────────────────────────────────────────
function Audience() {
  return (
    <section style={{
      background: T.bg, borderBottom: `1px solid ${T.border2}`,
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '80px 48px' }}>
        <div className="audience-section">
          {/* Left: heading */}
          <div style={{ flex: '0 0 420px' }}>
            <p style={{ fontFamily: mono, fontSize: 12, color: T.amber, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: 12 }}>
              Who it's for
            </p>
            <h2 style={{ fontFamily: sans, fontWeight: 700, fontSize: 36, margin: '0 0 4px', color: T.text }}>
              Built for researchers,
            </h2>
            <h2 style={{ fontFamily: serif, fontStyle: 'italic', fontWeight: 700, fontSize: 36, color: T.amber, margin: '0 0 24px' }}>
              not sysadmins.
            </h2>
            <p style={{ fontFamily: sans, fontSize: 18, color: T.muted, lineHeight: 1.7, maxWidth: 380 }}>
              If you spend more time formatting{' '}
              <span style={{ color: T.amber, fontFamily: mono }}>#SBATCH</span>{' '}
              directives than thinking about your science, ClusterPilot is for you.{' '}
              <strong style={{ color: T.text }}>
                Works with any standard SLURM cluster – Compute Canada, NSF ACCESS, ARCHER2, EuroHPC, and most university systems.
              </strong>
            </p>
          </div>

          {/* Right: audience items */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 0 }}>
            {AUDIENCE.map((item, i) => (
              <div key={item.n} style={{
                display: 'flex', gap: 20, padding: '20px 0',
                borderBottom: i < AUDIENCE.length - 1 ? `1px solid ${T.border2}` : 'none',
                alignItems: 'flex-start',
              }}>
                <span style={{ fontFamily: mono, fontSize: 12, color: T.amber, flexShrink: 0, marginTop: 2 }}>
                  {item.n}
                </span>
                <div>
                  <p style={{ fontFamily: sans, fontWeight: 600, fontSize: 17, color: T.text, marginBottom: 4 }}>
                    {item.title}
                  </p>
                  <p style={{ fontFamily: sans, fontSize: 16, color: T.muted, lineHeight: 1.6 }}>
                    {item.sub}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

// ─── pricing ──────────────────────────────────────────────────────────────────
function PricingCard({ badge, title, price, priceSub, desc, features, cta, ctaHref, featured, groupNote }) {
  const [btnHovered, setBtnHovered] = useState(false)

  return (
    <div style={{
      background: T.bg3, border: `1px solid ${featured ? T.amber : T.border}`,
      borderRadius: 8, padding: 36, display: 'flex', flexDirection: 'column',
    }}>
      <p style={{ fontFamily: mono, fontSize: 13, color: featured ? T.amber : T.muted, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: 12 }}>
        {badge}
      </p>
      <h3 style={{ fontFamily: sans, fontWeight: 700, fontSize: 24, color: T.text, marginBottom: 8 }}>
        {title}
      </h3>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 16 }}>
        <span style={{ fontFamily: mono, fontSize: 40, fontWeight: 500, color: T.text }}>{price}</span>
        <span style={{ fontFamily: mono, fontSize: 15, color: T.muted }}>{priceSub}</span>
      </div>
      <p style={{ fontFamily: sans, fontSize: 17, color: T.muted, lineHeight: 1.65, marginBottom: 24 }}>{desc}</p>
      <hr style={{ border: 'none', borderTop: `1px solid ${T.border}`, marginBottom: 24 }} />
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 28 }}>
        {features.map(f => (
          <div key={f} style={{ display: 'flex', alignItems: 'flex-start', gap: 10, fontFamily: sans, fontSize: 16, color: T.text }}>
            <span style={{ color: T.amber, flexShrink: 0, marginTop: 1 }}>✓</span>
            {f}
          </div>
        ))}
      </div>
      {groupNote && (
        <p style={{ fontFamily: sans, fontSize: 13, color: T.muted, marginBottom: 16, lineHeight: 1.5 }}>
          {groupNote}
        </p>
      )}
      <a href={ctaHref} target="_blank" rel="noreferrer">
        <button
          onMouseEnter={() => setBtnHovered(true)}
          onMouseLeave={() => setBtnHovered(false)}
          style={{
            background: featured
              ? T.amber
              : btnHovered ? T.amber : 'transparent',
            color: featured
              ? '#000'
              : btnHovered ? '#000' : T.text,
            fontFamily: mono, fontWeight: 700, fontSize: 14,
            padding: '12px 0', borderRadius: 6, border: `1px solid ${T.amber}`,
            cursor: 'pointer', width: '100%',
            transition: 'background 0.2s, color 0.2s',
          }}
        >
          {cta}
        </button>
      </a>
    </div>
  )
}

function Pricing() {
  return (
    <section id="pricing" style={{
      background: T.bg, borderBottom: `1px solid ${T.amber}33`,
    }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '80px 48px' }}>
        <p style={{ fontFamily: mono, fontSize: 12, color: T.amber, letterSpacing: '1.5px', textTransform: 'uppercase', marginBottom: 12 }}>
          Pricing
        </p>
        <h2 style={{ fontFamily: sans, fontWeight: 700, fontSize: 36, margin: '0 0 4px', color: T.text }}>
          Free forever for self-hosters.
        </h2>
        <h2 style={{ fontFamily: serif, fontStyle: 'italic', fontWeight: 700, fontSize: 36, color: T.amber, margin: 0 }}>
          Hosted tier: now live.
        </h2>

        <div className="pricing-grid">
          <PricingCard
            badge="Current"
            title="Self-hosted"
            price="Free"
            priceSub="forever"
            desc="Bring your own AI provider API key. Full functionality, no limitations. MIT licence – use it, fork it, extend it."
            features={[
              'Full TUI – submit, monitor, sync',
              'AI script generation (your API key)',
              'SSH ControlMaster integration',
              'Push notifications via ntfy.sh',
              'Background daemon + systemd service',
              'Open source, MIT licence',
            ]}
            cta="Get started on GitHub →"
            ctaHref="https://github.com/ju-pixel/clusterpilot"
            featured={true}
          />
          <PricingCard
            badge="New"
            title="Hosted"
            price="$3"
            priceSub="/ month"
            desc="Zero setup. Managed API key, web dashboard, and cloud sync across all your machines. For researchers who want it to just work."
            features={[
              'Everything in Self-hosted',
              'Managed API key – no Anthropic account needed',
              'Web dashboard for job history',
              'Multi-machine sync – one view across all your clusters',
              'Priority support',
            ]}
            groupNote={<>Research group? <strong style={{ color: T.amber }}>15% off</strong> for 3 or more seats. Buy from the dashboard after signing in.</>}
            cta="Get started →"
            ctaHref="https://app.clusterpilot.sh"
            featured={false}
          />
        </div>
      </div>
    </section>
  )
}

// ─── fieldnotes cross-link ────────────────────────────────────────────────────
function FieldnotesSection() {
  const blue = '#3D74F6'
  return (
    <section style={{ background: T.bg, borderTop: `1px solid ${T.border2}` }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '52px 48px', textAlign: 'center' }}>
        <p style={{ fontFamily: mono, fontSize: 13, color: T.muted, marginBottom: 24, letterSpacing: '0.02em' }}>
          Also building
        </p>
        <a href="https://fieldnotes.sh" target="_blank" rel="noreferrer"
          style={{ display: 'inline-flex', alignItems: 'center', gap: 10, textDecoration: 'none', marginBottom: 14 }}>
          <svg width={32} height={32} viewBox="0 0 22 22" fill="none">
            <rect x="4" y="2" width="14" height="18" rx="2" stroke={blue} strokeWidth="1.3" fill="none"/>
            <rect x="4" y="2" width="3" height="18" rx="1.5" fill={blue} fillOpacity="0.4"/>
            <line x1="9" y1="7"    x2="16" y2="7"    stroke="#fafafa" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.5"/>
            <line x1="9" y1="10.5" x2="16" y2="10.5" stroke="#fafafa" strokeWidth="1" strokeLinecap="round" strokeOpacity="0.3"/>
            <line x1="9" y1="14"   x2="13" y2="14"   stroke={T.amber} strokeWidth="1" strokeLinecap="round" strokeOpacity="0.7"/>
            <circle cx="16.5" cy="16.5" r="3.5" fill={T.bg} stroke={T.amber} strokeWidth="1.2"/>
            <line x1="15.5" y1="16.5" x2="17.5" y2="16.5" stroke={T.amber} strokeWidth="1" strokeLinecap="round"/>
            <line x1="16.5" y1="15.5" x2="16.5" y2="17.5" stroke={T.amber} strokeWidth="1" strokeLinecap="round"/>
          </svg>
          <span style={{ fontFamily: mono, fontSize: 26, letterSpacing: '-0.3px' }}>
            <span style={{ color: '#fafafa' }}>field</span><span style={{ color: blue }}>notes</span>
          </span>
        </a>
        <p style={{ fontFamily: mono, fontSize: 14, color: T.muted, letterSpacing: '0.02em' }}>
          permanent run records for computational researchers.
        </p>
      </div>
    </section>
  )
}

// ─── footer ───────────────────────────────────────────────────────────────────
function Footer() {
  return (
    <footer style={{ background: T.bg }}>
      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '40px 48px' }}>
        <div className="footer-inner">
          <a href="/" style={{ display: 'flex', alignItems: 'center', gap: 8, textDecoration: 'none' }}>
            <img src="/logo.png" alt="ClusterPilot" width={28} height={28} />
            <span style={{ fontFamily: mono, fontSize: 16, color: T.amber }}>clusterpilot</span>
          </a>
          <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
            {[
              ['GitHub', 'https://github.com/ju-pixel/clusterpilot'],
              ['PyPI', 'https://pypi.org/project/clusterpilot/'],
              ['Blog', '/blog'],
              ['Support', '/support'],
              ['juliafrank.net', 'https://juliafrank.net'],
              ['MIT Licence', 'https://github.com/ju-pixel/clusterpilot?tab=MIT-1-ov-file#readme'],
            ].map(([label, href]) => (
              <a key={label} href={href}
                target={href.startsWith('http') ? '_blank' : undefined}
                rel={href.startsWith('http') ? 'noreferrer' : undefined}
                style={{ fontFamily: mono, fontSize: 13, color: T.muted, textDecoration: 'none' }}
                onMouseEnter={e => e.currentTarget.style.color = T.text}
                onMouseLeave={e => e.currentTarget.style.color = T.muted}
              >
                {label}
              </a>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginTop: 16, borderTop: `1px solid ${T.border2}`, paddingTop: 16, width: '100%' }}>
            {[
              ['Privacy Policy', '/privacy'],
              ['Terms of Service', '/terms'],
              ['Data Processing Agreement', '/dpa'],
              ['Acceptable Use Policy', '/acceptable-use'],
            ].map(([label, href]) => (
              <a key={label} href={href}
                style={{ fontFamily: mono, fontSize: 12, color: T.dim, textDecoration: 'none' }}
                onMouseEnter={e => e.currentTarget.style.color = T.muted}
                onMouseLeave={e => e.currentTarget.style.color = T.dim}
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

// ─── page ─────────────────────────────────────────────────────────────────────
export default function LandingPage() {
  return (
    <div style={{ background: T.bg, color: T.text, minHeight: '100vh' }}>
      <Nav />
      <Hero />
      <TuiShowcase />
      <HowItWorks />
      <Features />
      <Audience />
      <Pricing />
      <FieldnotesSection />
      <Footer />
    </div>
  )
}
