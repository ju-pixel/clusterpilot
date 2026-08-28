// ─── blog post index ──────────────────────────────────────────────────────────
// Posts are authored as markdown files in frontend/content/blog/, one per file,
// named YYYY-MM-DD-slug.md with YAML-style frontmatter. This module loads them at
// build time, parses the frontmatter, converts the markdown body to HTML, and
// exports the same shape BlogPage.jsx has always consumed:
//   { slug, title, date, excerpt, description, category, image, imageAlt,
//     content (HTML), draft }
// plus getPost(slug). Nothing else in the app needs to change when a post is added.
//
// To add a post: drop a markdown file in frontend/content/blog/. See the repo
// CLAUDE.md ("Adding a blog post") for the frontmatter schema.

import { marked } from 'marked'
// The flat `key: value` frontmatter parser lives in ../markdown/frontmatter.js, shared
// with the docs loader. We do NOT use gray-matter because it assumes Node Buffers
// and does not run in the browser bundle.
import { parseFrontmatter } from '../markdown/frontmatter'

// Eagerly pull every markdown file in as a raw string. import.meta.glob works in
// dev, the client build, and the SSR build, so the loader is identical everywhere.
const files = import.meta.glob('../../content/blog/*.md', {
  eager: true,
  query: '?raw',
  import: 'default',
})

// ─── file → post ────────────────────────────────────────────────────────────────
function toPost(filePath, raw) {
  const { data, body } = parseFrontmatter(raw)
  // Slug is the filename without the .md extension, e.g. 2026-07-14-test-post.
  const slug = filePath.split('/').pop().replace(/\.md$/, '')
  const description = data.description ?? ''
  return {
    slug,
    title: data.title ?? '',
    date: data.date ?? '',
    description,
    excerpt: data.excerpt ?? description,
    category: data.category ?? '',
    image: data.image ?? '',
    imageAlt: data.imageAlt ?? '',
    content: marked.parse(body ?? ''),
    draft: data.draft === true,
  }
}

let all = Object.entries(files).map(([filePath, raw]) => toPost(filePath, raw))

// Hide drafts in production builds only; keep them visible in dev so they can be
// previewed while being written.
if (import.meta.env.PROD) {
  all = all.filter(post => !post.draft)
}

// Newest first, by the frontmatter date (string compare is safe for YYYY-MM-DD).
all.sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))

export const posts = all

export function getPost(slug) {
  return posts.find(p => p.slug === slug) ?? null
}
