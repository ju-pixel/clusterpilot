// ─── postbuild: prerender the blog + generate sitemap and RSS ───────────────────
// Runs after `vite build` (client) and `vite build --ssr` (SSR bundle). It turns
// the blog routes into standalone static HTML documents with real meta tags, and
// regenerates dist/sitemap.xml and dist/rss.xml. No JavaScript bundle is injected
// into the blog pages: they are plain, fully-rendered documents.
//
// Zero-posts case is handled: /blog is still emitted, the sitemap still lists the
// static routes, and a valid (item-less) RSS channel is written.

import { readFile, writeFile, mkdir, readdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SITE = 'https://clusterpilot.sh'
const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(scriptDir, '..') // frontend/
const dist = path.join(root, 'dist')
const distSsr = path.join(root, 'dist-ssr')

// Static routes that exist as SPA pages, mirrored into the sitemap.
const STATIC_ROUTES = [
  { loc: '/', priority: '1.0', changefreq: 'weekly' },
  // File-backed routes carry a trailing slash (Netlify 301s the slash-less
  // form to the directory); SPA catch-all routes stay slash-less.
  { loc: '/blog/', priority: '0.7', changefreq: 'weekly' },
  { loc: '/support', priority: '0.5', changefreq: 'monthly' },
  { loc: '/privacy', priority: '0.3', changefreq: 'yearly' },
  { loc: '/terms', priority: '0.3', changefreq: 'yearly' },
  { loc: '/dpa', priority: '0.2', changefreq: 'yearly' },
  { loc: '/acceptable-use', priority: '0.3', changefreq: 'yearly' },
]

// ─── helpers ──────────────────────────────────────────────────────────────────────
function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// XML text escaping for sitemap/RSS values (RSS descriptions are plain text here).
function escapeXml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&apos;')
}

// Resolve the SSR bundle entry file (Vite names it entry-prerender.js/.mjs).
async function resolveSsrEntry() {
  const entries = await readdir(distSsr)
  const match = entries.find(f => /^entry-prerender.*\.(mjs|js)$/.test(f))
  if (!match) {
    throw new Error(`Could not find the SSR entry in ${distSsr} (got: ${entries.join(', ')})`)
  }
  return path.join(distSsr, match)
}

// Pull the styling/font <link> tags out of the client index.html so the static
// blog pages resolve the same CSS and fonts. Tolerant of attribute order and of
// there being more than one stylesheet link.
function extractHeadLinks(indexHtml) {
  const links = indexHtml.match(/<link\b[^>]*>/gi) ?? []
  return links.filter(tag =>
    /rel=["'](stylesheet|preconnect|preload)["']/i.test(tag),
  )
}

// Build one standalone HTML document from the rendered body markup + head object.
function buildDocument({ head, styleLinks, bodyHtml }) {
  const ogTags = Object.entries(head.ogTags)
    .map(([prop, val]) => `    <meta property="${prop}" content="${escapeHtml(val)}" />`)
    .join('\n')

  // Twitter card tags use name= (not property=). Tolerate heads without any.
  const twitterTags = Object.entries(head.twitterTags ?? {})
    .map(([name, val]) => `    <meta name="${name}" content="${escapeHtml(val)}" />`)
    .join('\n')

  return `<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>${escapeHtml(head.title)}</title>
    <meta name="description" content="${escapeHtml(head.description)}" />
    <link rel="canonical" href="${escapeHtml(head.canonical)}" />
${ogTags}
${twitterTags}
    <link rel="icon" type="image/png" href="/logo.png" />
${styleLinks.map(l => '    ' + l).join('\n')}
  </head>
  <body>
    <div id="root">${bodyHtml}</div>
  </body>
</html>
`
}

// Map a URL to its output file path under dist/.
function outputPathFor(url) {
  if (url === '/blog') return path.join(dist, 'blog', 'index.html')
  const slug = url.replace(/^\/blog\//, '').replace(/\/$/, '')
  return path.join(dist, 'blog', slug, 'index.html')
}

// ─── sitemap and RSS ──────────────────────────────────────────────────────────────
function buildSitemap(postUrls) {
  const staticEntries = STATIC_ROUTES.map(
    r => `  <url>
    <loc>${SITE}${r.loc}</loc>
    <changefreq>${r.changefreq}</changefreq>
    <priority>${r.priority}</priority>
  </url>`,
  )
  const postEntries = postUrls.map(
    ({ slug, date }) => `  <url>
    <loc>${SITE}/blog/${escapeXml(slug)}/</loc>
    <lastmod>${escapeXml(date)}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>`,
  )
  return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${[...staticEntries, ...postEntries].join('\n')}
</urlset>
`
}

function toRfc822(dateStr) {
  const d = new Date(`${dateStr}T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? new Date().toUTCString() : d.toUTCString()
}

function buildRss(items) {
  const rssItems = items
    .map(
      p => `    <item>
      <title>${escapeXml(p.title)}</title>
      <link>${SITE}/blog/${escapeXml(p.slug)}/</link>
      <guid>${SITE}/blog/${escapeXml(p.slug)}/</guid>
      <description>${escapeXml(p.description)}</description>
      <pubDate>${toRfc822(p.date)}</pubDate>
    </item>`,
    )
    .join('\n')

  return `<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ClusterPilot blog</title>
    <link>${SITE}/blog/</link>
    <description>Practical guides, SLURM gotchas, and notes on building tools for computational researchers.</description>
    <language>en-GB</language>
${rssItems}
  </channel>
</rss>
`
}

// ─── main ─────────────────────────────────────────────────────────────────────────
async function main() {
  const ssrEntry = await resolveSsrEntry()
  const { render, urls, postsMeta } = await import(pathToFileURL(ssrEntry).href)

  const indexHtml = await readFile(path.join(dist, 'index.html'), 'utf8')
  const styleLinks = extractHeadLinks(indexHtml)
  if (styleLinks.length === 0) {
    console.warn('postbuild: no stylesheet/font links found in dist/index.html')
  }

  // Prerender every content URL into a standalone static document.
  for (const url of urls) {
    const { html, head } = render(url)
    const doc = buildDocument({ head, styleLinks, bodyHtml: html })
    const outPath = outputPathFor(url)
    await mkdir(path.dirname(outPath), { recursive: true })
    await writeFile(outPath, doc, 'utf8')
    console.log(`postbuild: wrote ${path.relative(dist, outPath)}`)
  }

  // sitemap and RSS from the loader's real post metadata (zero-posts safe).
  await writeFile(path.join(dist, 'sitemap.xml'), buildSitemap(postsMeta), 'utf8')
  await writeFile(path.join(dist, 'rss.xml'), buildRss(postsMeta), 'utf8')
  console.log(`postbuild: wrote sitemap.xml and rss.xml (${postsMeta.length} post(s))`)
}

main().catch(err => {
  console.error('postbuild failed:', err)
  process.exit(1)
})
