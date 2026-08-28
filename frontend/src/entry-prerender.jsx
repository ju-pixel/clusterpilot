// ─── prerender entry ─────────────────────────────────────────────────────────
// Built by `vite build --ssr src/entry-prerender.jsx` into dist-ssr/. The postbuild
// script imports this module, calls render(url) for each URL in `urls`, and writes
// the returned markup into standalone static HTML documents with proper meta tags.
//
// react-router v7 ships StaticRouter from the main entry (re-exported by
// react-router-dom); there is no separate react-router-dom/server subpath here.

import { renderToStaticMarkup } from 'react-dom/server'
import { StaticRouter, Routes, Route } from 'react-router-dom'
import BlogPage from './blog/BlogPage'
import DocsPage from './docs/DocsPage'
import { posts, getPost } from './blog/posts'
import { docs, getDoc } from './docs/docs'

const SITE = 'https://clusterpilot.sh'

// Keep titles readable in search results. Only append the brand suffix when it
// still fits comfortably under ~60 characters.
function withSuffix(title) {
  const suffix = ' | ClusterPilot'
  return title.length + suffix.length <= 60 ? title + suffix : title
}

// ─── head builders ──────────────────────────────────────────────────────────────
function headForIndex() {
  const title = 'ClusterPilot blog'
  const description =
    'Practical guides, SLURM gotchas, and notes on building tools for computational researchers, from the team behind ClusterPilot.'
  // Trailing slash: Netlify 301s the slash-less URL to the directory form,
  // so the canonical must be the URL that actually serves.
  const canonical = `${SITE}/blog/`
  return {
    title,
    description,
    canonical,
    ogTags: {
      'og:title': title,
      'og:description': description,
      'og:type': 'website',
      'og:url': canonical,
    },
    twitterTags: { 'twitter:card': 'summary' },
  }
}

function headForPost(post, slug) {
  const canonical = `${SITE}/blog/${slug}/`
  const title = withSuffix(post.title)
  const description = post.description || post.excerpt || ''
  const ogTags = {
    'og:title': post.title,
    'og:description': description,
    'og:type': 'article',
    'og:url': canonical,
  }
  // A post with a featured image gets a rich, large-image social card; posts
  // without one fall back to a plain summary card and emit no og:image. The
  // frontmatter `image` is a site-absolute path (e.g. /images/blog/slug.png).
  const twitterTags = { 'twitter:card': 'summary' }
  if (post.image) {
    ogTags['og:image'] = `${SITE}${post.image}`
    if (post.imageAlt) ogTags['og:image:alt'] = post.imageAlt
    twitterTags['twitter:card'] = 'summary_large_image'
  }
  return { title, description, canonical, ogTags, twitterTags }
}

function headForDocsIndex() {
  const title = 'ClusterPilot docs'
  const description =
    'Guides to installing ClusterPilot, submitting SLURM jobs, and getting more out of your cluster: storage, job efficiency, and GPU requests.'
  const canonical = `${SITE}/docs/`
  return {
    title,
    description,
    canonical,
    ogTags: {
      'og:title': title,
      'og:description': description,
      'og:type': 'website',
      'og:url': canonical,
    },
    twitterTags: { 'twitter:card': 'summary' },
  }
}

function headForDoc(doc, slug) {
  const canonical = `${SITE}/docs/${slug}/`
  const description = doc.excerpt || ''
  // Docs pages carry no featured image, so the card is always a plain summary
  // and no og:image is emitted.
  return {
    title: withSuffix(doc.title),
    description,
    canonical,
    ogTags: {
      'og:title': doc.title,
      'og:description': description,
      'og:type': 'article',
      'og:url': canonical,
    },
    twitterTags: { 'twitter:card': 'summary' },
  }
}

// ─── render ──────────────────────────────────────────────────────────────────────
export function render(url) {
  const html = renderToStaticMarkup(
    <StaticRouter location={url}>
      <Routes>
        <Route path="/blog" element={<BlogPage />} />
        <Route path="/blog/:slug" element={<BlogPage />} />
        <Route path="/docs" element={<DocsPage />} />
        <Route path="/docs/:slug" element={<DocsPage />} />
      </Routes>
    </StaticRouter>,
  )

  let head
  if (url === '/blog') {
    head = headForIndex()
  } else if (url === '/docs') {
    head = headForDocsIndex()
  } else if (url.startsWith('/docs/')) {
    const slug = url.replace(/^\/docs\//, '').replace(/\/$/, '')
    const doc = getDoc(slug)
    head = doc ? headForDoc(doc, slug) : headForDocsIndex()
  } else {
    const slug = url.replace(/^\/blog\//, '').replace(/\/$/, '')
    const post = getPost(slug)
    head = post ? headForPost(post, slug) : headForIndex()
  }

  return { html, head }
}

// The set of routes to prerender: both index pages plus one page per (non-draft
// in production) post and doc. `posts` and `docs` are already filtered and sorted
// by their loaders.
export const urls = [
  '/blog',
  ...posts.map(p => `/blog/${p.slug}`),
  '/docs',
  ...docs.map(d => `/docs/${d.slug}`),
]

// Lean post metadata for the postbuild script's sitemap and RSS generation. Same
// filtering and ordering as `posts`; the HTML body is deliberately left out.
export const postsMeta = posts.map(p => ({
  slug: p.slug,
  title: p.title,
  date: p.date,
  description: p.description || p.excerpt || '',
}))

// Lean docs metadata for the postbuild script's sitemap generation. Docs are not
// in the RSS feed, which stays blog-only.
export const docsMeta = docs.map(d => ({
  slug: d.slug,
  title: d.title,
  description: d.excerpt || '',
}))
