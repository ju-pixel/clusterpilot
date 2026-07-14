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
import { posts, getPost } from './blog/posts'

const SITE = 'https://clusterpilot.sh'

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
  // Keep titles readable in search results. Only append the brand suffix when it
  // still fits comfortably under ~60 characters.
  const suffix = ' | ClusterPilot'
  const title =
    post.title.length + suffix.length <= 60 ? post.title + suffix : post.title
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

// ─── render ──────────────────────────────────────────────────────────────────────
export function render(url) {
  const html = renderToStaticMarkup(
    <StaticRouter location={url}>
      <Routes>
        <Route path="/blog" element={<BlogPage />} />
        <Route path="/blog/:slug" element={<BlogPage />} />
      </Routes>
    </StaticRouter>,
  )

  let head
  if (url === '/blog') {
    head = headForIndex()
  } else {
    const slug = url.replace(/^\/blog\//, '').replace(/\/$/, '')
    const post = getPost(slug)
    head = post ? headForPost(post, slug) : headForIndex()
  }

  return { html, head }
}

// The set of routes to prerender: the blog index plus one page per (non-draft in
// production) post. `posts` is already filtered and sorted by the loader.
export const urls = ['/blog', ...posts.map(p => `/blog/${p.slug}`)]

// Lean post metadata for the postbuild script's sitemap and RSS generation. Same
// filtering and ordering as `posts`; the HTML body is deliberately left out.
export const postsMeta = posts.map(p => ({
  slug: p.slug,
  title: p.title,
  date: p.date,
  description: p.description || p.excerpt || '',
}))
