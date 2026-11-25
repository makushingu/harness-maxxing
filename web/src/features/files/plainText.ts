// The words of a file without its marks, for "Copy as plain text" (copyText.tsx): Markdown and HTML as a reader
// sees them, a workbook as cells separated by tabs (pastes into a spreadsheet). Loaded on the first copy.
import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'
import type { FileSheet } from '@/lib/types'

/** A node of the Markdown tree (mdast), as loose as this file needs it. */
type Md = {
  type: string
  value?: string
  children?: Md[]
  url?: string
  alt?: string | null
  ordered?: boolean | null
  start?: number | null
  spread?: boolean | null
  checked?: boolean | null
  identifier?: string
  label?: string | null
}

// Trims written as loops: an anchored regex (/\s+$/) is quadratic on a long run of blanks that is not at the end.
const isBlank = (c: string) => c === ' ' || c === '\t' || c === '\n' || c === '\r' || c === '\f' || c === '\v' || /\s/.test(c)
/** `s` without the characters `drop` accepts at its end. */
function cutEnd(s: string, drop: (c: string) => boolean): string {
  let b = s.length
  while (b > 0 && drop(s[b - 1])) b--
  return b === s.length ? s : s.slice(0, b)
}
/** No empty line around the text; a first row that starts with an empty cell keeps its tab. */
function edges(s: string): string {
  let a = 0
  while (a < s.length && s[a] === '\n') a++
  return cutEnd(s.slice(a), isBlank)
}
const isSpace = (c: string) => c === ' ' || c === '\t'
/** Line breaks at the end of `s`. */
function endBreaks(s: string): number {
  let n = 0
  while (n < s.length && s[s.length - 1 - n] === '\n') n++
  return n
}
/** The lines of a text cut in the source joined into one sentence: each line break and the blanks around it
 *  become one space, in linear time (a regex for it is quadratic on a long run of blanks). */
function oneLine(s: string): string {
  if (!s.includes('\n')) return s
  const parts = s.split('\n')
  const last = parts.length - 1
  const kept = parts.map((x, i) => (i > 0 ? x.trimStart() : x)).map((x, i) => (i < last ? x.trimEnd() : x))
  return kept.filter((x, i) => i === 0 || i === last || x).join(' ')
}

/** Above this size the Markdown is not parsed (seconds on the page's thread): its marks are taken off line by line. */
export const MD_PARSE_MAX = 200_000

export function markdownToText(md: string): string {
  if (md.length > MD_PARSE_MAX) return markdownToTextLight(md)
  const tree = unified().use(remarkParse).use(remarkGfm).parse(md) as Md
  return edges(mdBlocks(tree.children, '\n\n'))
}

/** A longer line is left as it is (the inline patterns are bounded, they stay fast on the others). */
const LIGHT_LINE_MAX = 10_000
/** The words of a big Markdown text without a parser, line by line: headings, quotes, fences, emphasis, code
 *  and links lose their marks (a link to a web or mail address keeps it in parentheses), lists keep `- `. */
export function markdownToTextLight(md: string): string {
  const out: string[] = []
  let fence = false
  for (let line of md.split('\n')) {
    line = cutEnd(line, (c) => c === '\r')
    if (/^ {0,3}(```|~~~)/.test(line)) {
      fence = !fence
      continue
    }
    if (fence || line.length > LIGHT_LINE_MAX) {
      out.push(line)
      continue
    }
    line = line
      .replace(/^ {0,3}(> ?)+/, '')
      .replace(/^ {0,3}#{1,6}(\s+|$)/, '')
      .replace(/^(\s*)[*+](\s+)/, '$1-$2')
      .replace(/^ {0,3}([-*_] *){3,}$/, '')
      .replace(/!\[([^\]]{0,300})\]\([^)]{0,2000}\)/g, '$1')
      .replace(/\[([^\]]{0,300})\]\(([^)\s]{0,2000})[^)]{0,300}\)/g, (_m, text: string, url: string) =>
        !/^(https?:|mailto:)/i.test(url) || url === text || url === `mailto:${text}` ? text : text ? `${text} (${url})` : url)
      .replace(/`([^`]{0,300})`/g, '$1')
      .replace(/(\*\*|__)([^*_]{1,300})\1/g, '$2')
      .replace(/~~([^~]{1,300})~~/g, '$1')
      .replace(/\*([^*\s][^*]{0,300})\*/g, '$1')
    out.push(line)
  }
  return edges(out.join('\n'))
}

const mdBlocks = (nodes: Md[] | undefined, sep: string) => (nodes ?? []).map(mdBlock).filter(Boolean).join(sep)

function mdBlock(n: Md): string {
  switch (n.type) {
    case 'heading':
    case 'paragraph':
      return mdInline(n).trim()
    case 'code':
      return n.value ?? ''
    case 'html':
      return htmlToText(n.value ?? '')
    case 'thematicBreak':
    case 'definition':
      return ''
    case 'list': {
      let i = n.start ?? 1
      return (n.children ?? [])
        .map((li) => {
          const mark = (n.ordered ? `${i++}. ` : '- ') + (li.checked == null ? '' : li.checked ? '[x] ' : '[ ] ')
          // what follows the first line of an item stays under its text
          return mark + mdBlocks(li.children, li.spread ? '\n\n' : '\n').replace(/\n(?=[^\n])/g, '\n' + ' '.repeat(mark.length))
        })
        .join(n.spread ? '\n\n' : '\n')
    }
    case 'table':
      return (n.children ?? []).map((row) => (row.children ?? []).map((cell) => mdInline(cell).replace(/\s+/g, ' ').trim()).join('\t')).join('\n')
    case 'footnoteDefinition':
      return `[${n.label ?? n.identifier ?? ''}] ${mdBlocks(n.children, '\n\n')}`
    default:
      return n.children ? mdBlocks(n.children, '\n\n') : (n.value ?? '')
  }
}

function mdInline(n: Md): string {
  switch (n.type) {
    case 'text':
      return oneLine(n.value ?? '') // a line cut in the source is one sentence for the reader
    case 'inlineCode':
      return n.value ?? ''
    case 'break':
      return '\n'
    case 'image':
    case 'imageReference':
      return n.alt ?? ''
    case 'html':
      return /^<br\s*\/?>$/i.test(n.value ?? '') ? '\n' : htmlToText(n.value ?? '')
    case 'footnoteReference':
      return `[${n.label ?? n.identifier ?? ''}]`
    case 'link': {
      const text = (n.children ?? []).map(mdInline).join('')
      const url = n.url ?? ''
      // the address is part of the words once the marks are gone (not a link inside the document or the server)
      if (!/^(https?:|mailto:)/i.test(url) || url === text || url === `mailto:${text}`) return text
      return text ? `${text} (${url})` : url
    }
    default:
      return (n.children ?? []).map(mdInline).join('')
  }
}

const HTML_SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'HEAD', 'SVG', 'IFRAME', 'OBJECT', 'CANVAS', 'VIDEO', 'AUDIO'])
/** Blocks set apart by an empty line, and blocks that only start a new line. */
const HTML_PARA = new Set(['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'PRE', 'BLOCKQUOTE', 'TABLE', 'HR', 'UL', 'OL', 'DL'])
const HTML_LINE = new Set([
  'ADDRESS', 'ARTICLE', 'ASIDE', 'CAPTION', 'DD', 'DETAILS', 'DIV', 'DT', 'FIELDSET', 'FIGCAPTION', 'FIGURE', 'FOOTER', 'FORM',
  'HEADER', 'LI', 'MAIN', 'NAV', 'SECTION', 'SUMMARY', 'TR',
])

/** The text of an HTML page or fragment, read without running or loading anything of it. */
export function htmlToText(html: string): string {
  const doc = new DOMParser().parseFromString(html, 'text/html')
  // the text so far = done.join('') + out: the tests and trims below only ever read `out`, a short end that starts
  // with a word or a new line (a regex or a replace over the whole text at each block was quadratic: 87 s for 870 KB)
  const done: string[] = []
  let out = ''
  const empty = () => !out && !done.length
  const settle = () => {
    if (out.length < 2048) return
    let c = out.length - 512
    while (c > 0 && /\s/.test(out[c]) && out[c - 1] !== '\n') c-- // cut before a word or just after a line break
    if (c <= 0) return
    done.push(out.slice(0, c))
    out = out.slice(c)
  }
  /** At least `n` line breaks at the end (none before the first word, none between a list mark and its text). */
  const brk = (n: number, closing = false) => {
    if (!closing && /(^|\n) *(- |\d+\. )$/.test(out)) return
    out = cutEnd(out, isSpace)
    const have = endBreaks(out)
    if (!empty() && have < n) out += '\n'.repeat(n - have)
  }
  const items = new Map<Element, number>() // a list -> its items so far (counting the earlier ones each time: n²)
  const walk = (node: Node, pre: boolean) => {
    for (const c of Array.from(node.childNodes)) {
      if (c.nodeType === 3) {
        const s = c.nodeValue ?? ''
        if (pre) out += s
        else {
          const t = s.replace(/\s+/g, ' ')
          out += empty() || /\s$/.test(out) ? t.replace(/^ /, '') : t
        }
        settle()
        continue
      }
      if (c.nodeType !== 1) continue
      const el = c as Element
      const tag = el.tagName.toUpperCase()
      if (HTML_SKIP.has(tag)) continue
      if (tag === 'BR') {
        out = cutEnd(out, isSpace) + '\n'
        continue
      }
      if (tag === 'IMG') {
        out += el.getAttribute('alt') ?? ''
        settle()
        continue
      }
      // a list inside an item starts on the next line, not after an empty one
      const lines = HTML_PARA.has(tag) ? (el.parentElement?.closest('li') && (tag === 'UL' || tag === 'OL') ? 1 : 2) : HTML_LINE.has(tag) ? 1 : 0
      if (lines) brk(lines)
      if (tag === 'LI') {
        const list = el.parentElement
        for (let up = list?.closest('li'); up; up = up.parentElement?.closest('li')) out += '  ' // a list inside an item
        if (list?.tagName === 'OL') {
          const i = (items.get(list) ?? (Number(list.getAttribute('start')) || 1) - 1) + 1
          items.set(list, i)
          out += `${i}. `
        } else out += '- '
      } else if ((tag === 'TD' || tag === 'TH') && el.previousElementSibling) out = cutEnd(out, (ch) => ch === ' ') + '\t'
      walk(el, pre || tag === 'PRE')
      if (lines) brk(lines, true)
    }
  }
  walk(doc.body, false)
  done.push(out)
  return edges(done.join(''))
}

/** Cells separated by tabs, one row a line; several sheets: each under its name. */
export function sheetsToText(sheets: FileSheet[]): string {
  const cell = (c: string) => String(c ?? '').replace(/[\t\r\n]+/g, ' ')
  const text = sheets
    .map((s) => (sheets.length > 1 ? `${s.name}\n` : '') + s.rows.map((r) => r.map(cell).join('\t')).join('\n'))
    .join('\n\n')
  let a = 0
  while (a < text.length && text[a] === '\n') a++
  return cutEnd(text.slice(a), (c) => c === '\n')
}
