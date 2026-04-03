// ─── blog post index ──────────────────────────────────────────────────────────
// To add a post: append a new entry to this array. The `content` field is plain
// HTML (use <p>, <h2>, <pre>, <code>, <ul>, <li>, <strong>, <em>).
// `slug` must be unique and URL-safe.

export const posts = []

export function getPost(slug) {
  return posts.find(p => p.slug === slug) ?? null
}
