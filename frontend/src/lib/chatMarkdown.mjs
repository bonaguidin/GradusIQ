// A deliberately small Markdown reader for assistant replies.
//
// The model is asked for short paragraphs, '-' lists and **bold** at most, so
// this covers exactly that plus numbered lists, `code`, *italic* and links.
// It returns plain data, never HTML: ChatMarkdown.tsx turns it into React
// elements, so nothing the model writes is ever parsed as markup by the
// browser. Anything it does not recognise stays literal text.

const BULLET = /^\s*[-*•]\s+(.*)$/
const NUMBERED = /^\s*\d+[.)]\s+(.*)$/
const HEADING = /^\s*#{1,6}\s+(.*)$/

// Links are kept only when they point inside the app (a path) or to https.
// Anything else (javascript:, data:, mailto:, http:) renders as its text.
const SAFE_HREF = /^(\/(?!\/)[^\s]*|https:\/\/[^\s]+)$/

/** @typedef {{type:'text', text:string} | {type:'strong'|'em', children:Inline[]} | {type:'code', text:string} | {type:'link', href:string, children:Inline[]}} Inline */
/** @typedef {{type:'p', lines:Inline[][]} | {type:'ul'|'ol', items:Inline[][]}} Block */

const INLINE = /(\*\*([^*]+?)\*\*|__([^_]+?)__|`([^`]+?)`|\[([^\]]+?)\]\(([^)\s]+?)\)|\*([^*\s][^*]*?)\*)/

/**
 * @param {string} text
 * @returns {Inline[]}
 */
export function parseInline(text) {
  /** @type {Inline[]} */
  const out = []
  let rest = text
  while (rest) {
    const match = INLINE.exec(rest)
    if (!match) {
      out.push({ type: 'text', text: rest })
      break
    }
    if (match.index > 0) out.push({ type: 'text', text: rest.slice(0, match.index) })
    const [whole, , bold, boldAlt, code, linkText, href, em] = match
    if (bold !== undefined || boldAlt !== undefined) {
      out.push({ type: 'strong', children: parseInline(bold ?? boldAlt) })
    } else if (code !== undefined) {
      out.push({ type: 'code', text: code })
    } else if (linkText !== undefined) {
      out.push(
        SAFE_HREF.test(href)
          ? { type: 'link', href, children: parseInline(linkText) }
          : { type: 'text', text: linkText },
      )
    } else {
      out.push({ type: 'em', children: parseInline(em) })
    }
    rest = rest.slice(match.index + whole.length)
  }
  return out
}

/**
 * @param {string} source
 * @returns {Block[]}
 */
export function parseChatMarkdown(source) {
  /** @type {Block[]} */
  const blocks = []
  /** @type {Block | null} */
  let current = null

  for (const raw of source.replace(/\r\n?/g, '\n').split('\n')) {
    const line = raw.trimEnd()
    if (!line.trim()) {
      current = null
      continue
    }
    const bullet = BULLET.exec(line)
    const numbered = bullet ? null : NUMBERED.exec(line)
    if (bullet || numbered) {
      const type = bullet ? 'ul' : 'ol'
      if (!current || current.type !== type) {
        current = { type, items: [] }
        blocks.push(current)
      }
      current.items.push(parseInline((bullet ?? numbered)[1]))
      continue
    }
    // A heading the model wrote anyway reads as a bold line, not a big title.
    const heading = HEADING.exec(line)
    const inline = heading ? [{ type: 'strong', children: parseInline(heading[1]) }] : parseInline(line.trim())
    if (!current || current.type !== 'p') {
      current = { type: 'p', lines: [] }
      blocks.push(current)
    }
    current.lines.push(inline)
  }
  return blocks
}
