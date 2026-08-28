// ─── docs index ───────────────────────────────────────────────────────────────
// Pages are authored as markdown files in frontend/content/docs/, one per file,
// named <slug>.md with flat `key: value` frontmatter. This module loads them at
// build time, parses the frontmatter, converts the markdown body to HTML, and
// exports the shape DocsPage.jsx consumes:
//   { slug, category, title, excerpt, content (HTML), order, draft }
// plus CATEGORY_ORDER and getDoc(slug). Nothing else in the app changes when a
// page is added.
//
// To add a page: drop a markdown file in frontend/content/docs/. See the repo
// CLAUDE.md ("Adding a docs page") for the frontmatter schema. Do not add pages
// by editing this file.

import { marked } from 'marked'
import { parseFrontmatter } from '../lib/frontmatter'

// Sidebar grouping order. Each page has a `category`; the sidebar renders
// categories in this order and skips any that have no pages yet. Add new
// category names here to control where they appear.
export const CATEGORY_ORDER = [
  'Getting started',
  'Submitting jobs',
  'GPUs and clusters',
  'Integrations',
]

// Eagerly pull every markdown file in as a raw string. import.meta.glob works in
// dev, the client build, and the SSR build, so the loader is identical everywhere.
const files = import.meta.glob('../../content/docs/*.md', {
  eager: true,
  query: '?raw',
  import: 'default',
})

// ─── file → doc ─────────────────────────────────────────────────────────────────
function toDoc(filePath, raw) {
  const { data, body } = parseFrontmatter(raw)
  // Slug is the filename without the .md extension; docs carry no date prefix, so
  // the filename maps straight to the URL (/docs/<slug>).
  const slug = filePath.split('/').pop().replace(/\.md$/, '')
  const order = Number(data.order)
  return {
    slug,
    category: data.category ?? '',
    title: data.title ?? '',
    excerpt: data.excerpt ?? '',
    content: marked.parse(body ?? ''),
    // A missing or unparseable `order` sorts to the end of its category rather
    // than silently jumping to the front.
    order: Number.isNaN(order) ? 99 : order,
    draft: data.draft === true,
  }
}

let all = Object.entries(files).map(([filePath, raw]) => toDoc(filePath, raw))

// Hide drafts in production builds only; keep them visible in dev so they can be
// previewed while being written.
if (import.meta.env.PROD) {
  all = all.filter(doc => !doc.draft)
}

// Group by CATEGORY_ORDER, then by the `order` field within each category. Any
// category not listed in CATEGORY_ORDER sorts to the end, which matches how
// DocsPage renders unknown categories under "More".
const catIndex = cat => {
  const i = CATEGORY_ORDER.indexOf(cat)
  return i === -1 ? CATEGORY_ORDER.length : i
}
all.sort((a, b) => catIndex(a.category) - catIndex(b.category) || a.order - b.order)

export const docs = all

export function getDoc(slug) {
  return docs.find(d => d.slug === slug) ?? null
}
