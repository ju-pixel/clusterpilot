// ─── frontmatter parser ─────────────────────────────────────────────────────────
// A deliberately small parser for flat `key: value` frontmatter, shared by the
// blog loader (src/blog/posts.js) and the docs loader (src/docs/docs.js). We do
// NOT use gray-matter because it assumes Node Buffers and does not run in the
// browser bundle. Values are treated as strings, except the booleans true/false.
// Surrounding single or double quotes are stripped.
export function parseFrontmatter(raw) {
  const match = /^---\s*\r?\n([\s\S]*?)\r?\n---\s*\r?\n?([\s\S]*)$/.exec(raw)
  if (!match) return { data: {}, body: raw }

  const data = {}
  for (const line of match[1].split(/\r?\n/)) {
    if (!line.trim() || line.trim().startsWith('#')) continue
    const idx = line.indexOf(':')
    if (idx === -1) continue
    const key = line.slice(0, idx).trim()
    let value = line.slice(idx + 1).trim()
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1)
    }
    if (value === 'true') value = true
    else if (value === 'false') value = false
    data[key] = value
  }
  return { data, body: match[2] }
}
