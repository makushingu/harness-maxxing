import { fileThumbUrl } from '@/lib/queries/files'
import { FILE_HREF } from '@/features/files/viewerStore'
import {
  Bot,
  FileCode2,
  FilePen,
  FilePlus2,
  FileText,
  FolderSearch,
  Globe,
  ListTodo,
  type LucideIcon,
  Plug,
  Search,
  Sparkles,
  SquareTerminal,
  Wrench,
} from 'lucide-react'
import type { ClaudeModel, Session, Topic, WorkspaceTree } from '@/lib/types'

/** Fallback context window when the server does not know it yet (no turn reported it). */
export const CONTEXT_MAX = 200_000
/**
 * The window to measure against, from the most to the least specific:
 * 1. the model chosen for the NEXT turn, when it differs from the last one (its window as Claude Code
 *    reported it on this server - switching to a smaller model shows the risk before sending);
 * 2. the window reported by the last turn of this session;
 * 3. the window known for the last turn's model;
 * 4. a fallback: 200k, or 1M once the tokens already exceed 200k.
 */
export function contextWindow(
  tokens: number,
  reported: number | null | undefined,
  opts: { chosen?: string | null; real?: string | null; windows?: Record<string, number | null | undefined> } = {},
): number {
  const { chosen, real, windows = {} } = opts
  if (chosen && chosen !== real && windows[chosen]) return windows[chosen]!
  if (reported && reported > 0) return reported
  if (real && windows[real]) return windows[real]!
  return tokens > CONTEXT_MAX ? 1_000_000 : CONTEXT_MAX
}

/** "claude-sonnet-5-5" → "Sonnet 5.5" (falls back to the known label, then the raw id). */
export function modelLabel(id: string | null | undefined, models?: ClaudeModel[]): string {
  if (!id) return ''
  const known = models?.find((m) => m.id === id)
  if (known?.label) return known.label
  const m = /^claude-([a-z]+)-(\d+)(?:-(\d+))?/.exec(id)
  if (m) return `${m[1][0].toUpperCase()}${m[1].slice(1)} ${m[2]}${m[3] && m[3].length <= 2 ? `.${m[3]}` : ''}`
  return id
}

export function toolIcon(name: string): LucideIcon {
  if (name === 'Bash' || name === 'BashOutput' || name === 'KillShell') return SquareTerminal
  if (name === 'Read' || name === 'NotebookRead') return FileText
  if (name === 'Edit' || name === 'MultiEdit' || name === 'NotebookEdit') return FilePen
  if (name === 'Write') return FilePlus2
  if (name === 'Grep') return Search
  if (name === 'Glob' || name === 'LS') return FolderSearch
  if (name === 'WebFetch' || name === 'WebSearch') return Globe
  if (name === 'Task' || name === 'Agent') return Bot
  if (name === 'TodoWrite') return ListTodo
  if (name === 'Skill') return Sparkles
  if (name.startsWith('mcp__')) return Plug
  if (/code|notebook/i.test(name)) return FileCode2
  return Wrench
}

/** Display name of a topic path: "acme / blog" ("" = workspace root). */
export function topicLabel(path: string, rootLabel: string, sep = ' / '): string {
  if (!path) return rootLabel
  const m = /^projects\/([^/]+)(?:\/topics\/([^/]+))?$/.exec(path)
  if (m) return m[2] ? `${m[1]}${sep}${m[2]}` : m[1]
  return path
}

export function findTopic(ws: WorkspaceTree | undefined, path: string): Topic | undefined {
  for (const p of ws?.projects || []) for (const t of p.topics) if (t.path === path) return t
  return undefined
}

export function absTopicDir(ws: WorkspaceTree | undefined, path: string): string | null {
  if (!ws?.root) return null
  return path ? `${ws.root.replace(/\/$/, '')}/${path}` : ws.root
}

/** Base folders paths are shown relative to in tool cards (topic folder first, then the workspace). */
export type PathBases = { topicDir: string | null; wsRoot: string | null }

const reEscape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** An absolute path relative to the topic folder ("src/app.py", "." for the folder itself), else to the
 *  workspace ("~/projects/acme/…"), else unchanged. */
export function relPath(p: string, { topicDir, wsRoot }: PathBases): string {
  for (const [base, pre] of [
    [topicDir, ''],
    [wsRoot, '~/'],
  ] as const) {
    const b = base?.replace(/\/+$/, '')
    if (!b) continue
    if (p === b) return pre ? '~' : '.'
    if (p.startsWith(b + '/')) return pre + p.slice(b.length + 1)
  }
  return p
}

/** Same as relPath for every absolute path inside a one-line text (tool summaries, commands). */
export function relPaths(text: string, { topicDir, wsRoot }: PathBases): string {
  let out = text
  for (const [base, pre] of [
    [topicDir, ''],
    [wsRoot, '~/'],
  ] as const) {
    const b = base?.replace(/\/+$/, '')
    if (!b || b === '/') continue
    out = out.replace(new RegExp(`${reEscape(b)}(/|(?![\\w.-]))`, 'g'), (_m, slash: string) => (slash ? pre : pre ? '~' : '.'))
  }
  return out
}

export const sessionsUrl = (s: Pick<Session, 'id' | 'path'>) => `/sessions?path=${encodeURIComponent(s.path)}&session=${s.id}`

/* ---------------------------------------------------------------- File kinds */
const IMG = /\.(png|jpe?g|gif|webp|avif|bmp|svg|ico|heic|heif|tiff?)$/i
const VID = /\.(mp4|webm|mov|m4v|mkv|ogv|avi)$/i
const AUD = /\.(mp3|wav|ogg|oga|m4a|aac|flac|opus)$/i
export type FileKind = 'image' | 'video' | 'audio' | 'pdf' | 'markdown' | 'text'
export function fileKind(path: string, mime?: string): FileKind {
  if (IMG.test(path) || mime?.startsWith('image/')) return 'image'
  if (VID.test(path) || mime?.startsWith('video/')) return 'video'
  if (AUD.test(path) || mime?.startsWith('audio/')) return 'audio'
  if (/\.pdf$/i.test(path) || mime === 'application/pdf') return 'pdf'
  if (/\.(md|markdown|mdx)$/i.test(path)) return 'markdown'
  return 'text'
}
export const isImage = (p: string) => IMG.test(p)
export const isVideo = (p: string) => VID.test(p)
export const isAudio = (p: string) => AUD.test(p)
export const baseName = (p: string) => p.replace(/\/+$/, '').split('/').pop() || p
// Same URL builder as the viewer, so the viewer's instant placeholder is the thumbnail already in the cache.
export const thumbUrl = (p: string, w = 320) => fileThumbUrl(p, w)
export const rawUrl = (p: string, download = false) => `/api/files/raw?path=${encodeURIComponent(p)}${download ? '&download=1' : ''}`
export const filesUrl = (p: string) => `/files?path=${encodeURIComponent(p)}`

/* ---------------------------------------------------------------- Path linkification */
export { FILE_HREF }
const PATH_CHARS = "[^\\s`'\"()<>\\[\\]{}|,;*?]"
const TRAIL = /[.,:;!?)\]]+$/

/** Absolute paths inside `root` found in plain text → [start, end, path]. */
export function findPaths(text: string, root: string | null | undefined): [number, number, string][] {
  if (!root) return []
  const r = root.replace(/\/+$/, '') || '/'
  const re = new RegExp(`(?<![\\w\\]\\)/.~-])(/${PATH_CHARS}+)`, 'g')
  const out: [number, number, string][] = []
  for (const m of text.matchAll(re)) {
    let p = m[1]
    const trail = TRAIL.exec(p)
    if (trail) p = p.slice(0, -trail[0].length)
    if (p.length < 2) continue
    if (r !== '/' && p !== r && !p.startsWith(r + '/')) continue
    if (r === '/' && p.split('/').length < 3) continue
    out.push([m.index!, m.index! + p.length, p])
  }
  return out
}

/** Markdown with absolute file paths turned into preview links (`#mx-file=…`), code blocks untouched. */
export function linkifyMarkdown(md: string, root: string | null | undefined): string {
  if (!root || !md.includes('/')) return md
  const parts = md.split(/(```[\s\S]*?(?:```|$)|`[^`\n]+`)/g)
  return parts
    .map((part, i) => {
      if (i % 2 === 1) {
        if (part.startsWith('```')) return part
        const inner = part.slice(1, -1)
        const hits = findPaths(inner, root)
        if (hits.length === 1 && hits[0][0] === 0 && hits[0][1] === inner.length) return `[${part}](${FILE_HREF}${encodeURIComponent(inner)})`
        return part
      }
      const hits = findPaths(part, root)
      if (!hits.length) return part
      let out = ''
      let last = 0
      for (const [s, e, p] of hits) {
        // Skip paths that are already a markdown link target or text.
        if (part[s - 1] === '(' && part[s - 2] === ']') continue
        out += part.slice(last, s) + `[\`${p}\`](${FILE_HREF}${encodeURIComponent(p)})`
        last = e
      }
      return out + part.slice(last)
    })
    .join('')
}

/** Media paths mentioned in a text: images and videos (inline thumbnails), audio (inline players). */
export function mediaPaths(text: string, root: string | null | undefined, max = 6): string[] {
  return pathsOf(text, root, (p) => isImage(p) || isVideo(p), max)
}
export function audioPaths(text: string, root: string | null | undefined, max = 4): string[] {
  return pathsOf(text, root, isAudio, max)
}
function pathsOf(text: string, root: string | null | undefined, keep: (p: string) => boolean, max: number): string[] {
  const seen = new Set<string>()
  for (const [, , p] of findPaths(text, root)) if (keep(p)) seen.add(p)
  return [...seen].slice(0, max)
}

/* ---------------------------------------------------------------- Quotes */
/** A quoted file (right click -> Quote): one line `📎 /abs/path` - the path, never the file's content. */
export const FILE_QUOTE = '📎 '
export const fileQuote = (path: string) => FILE_QUOTE + path
/** The path of a quoted-file line, or null for a text quote. */
export const quotedFile = (q: string): string | null => (q.startsWith(FILE_QUOTE) && !q.includes('\n') && q.slice(FILE_QUOTE.length).startsWith('/') ? q.slice(FILE_QUOTE.length).trim() : null)

/** Quotes → Markdown blockquotes (`> ` on every line, blank lines kept as `>`), one block per quote. */
export function quotesMarkdown(quotes: string[]): string {
  return quotes.map((q) => q.split('\n').map((l) => (l.trim() ? `> ${l}` : '>')).join('\n')).join('\n\n')
}

/** Leading blockquotes of a user message (as sent by the composer) → quote texts + the rest of the message. */
export function splitQuotes(text: string): { quotes: string[]; rest: string } {
  if (!text.startsWith('>')) return { quotes: [], rest: text }
  const lines = text.split('\n')
  const quotes: string[] = []
  let cur: string[] | null = null
  let i = 0
  for (; i < lines.length; i++) {
    const l = lines[i]
    if (l.startsWith('>')) (cur ??= []).push(l.replace(/^> ?/, ''))
    else if (l.trim()) break
    else if (cur) {
      quotes.push(cur.join('\n').trim())
      cur = null
    }
  }
  if (cur) quotes.push(cur.join('\n').trim())
  return { quotes: quotes.filter(Boolean), rest: lines.slice(i).join('\n').trim() }
}

/* ---------------------------------------------------------------- Line diff (LCS) */
export type DiffLine = { t: ' ' | '-' | '+'; s: string }
export function lineDiff(a: string, b: string): DiffLine[] {
  const A = a.split('\n')
  const B = b.split('\n')
  // Trim the common prefix/suffix first: cheap and keeps the LCS table small.
  let pre = 0
  while (pre < A.length && pre < B.length && A[pre] === B[pre]) pre++
  let suf = 0
  while (suf < A.length - pre && suf < B.length - pre && A[A.length - 1 - suf] === B[B.length - 1 - suf]) suf++
  const a2 = A.slice(pre, A.length - suf)
  const b2 = B.slice(pre, B.length - suf)
  const head: DiffLine[] = A.slice(0, pre).map((s) => ({ t: ' ', s }))
  const tail: DiffLine[] = A.slice(A.length - suf).map((s) => ({ t: ' ', s }))
  let mid: DiffLine[]
  if (a2.length * b2.length > 250_000) {
    mid = [...a2.map((s) => ({ t: '-' as const, s })), ...b2.map((s) => ({ t: '+' as const, s }))]
  } else {
    const n = a2.length
    const m = b2.length
    const dp: Uint32Array[] = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1))
    for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) dp[i][j] = a2[i] === b2[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1])
    mid = []
    let i = 0
    let j = 0
    while (i < n && j < m) {
      if (a2[i] === b2[j]) {
        mid.push({ t: ' ', s: a2[i] })
        i++
        j++
      } else if (dp[i + 1][j] >= dp[i][j + 1]) mid.push({ t: '-', s: a2[i++] })
      else mid.push({ t: '+', s: b2[j++] })
    }
    while (i < n) mid.push({ t: '-', s: a2[i++] })
    while (j < m) mid.push({ t: '+', s: b2[j++] })
  }
  // Collapse long unchanged context to 3 lines around changes.
  const all = [...head, ...mid, ...tail]
  const keep = new Array(all.length).fill(false)
  all.forEach((l, k) => {
    if (l.t !== ' ') for (let d = -3; d <= 3; d++) if (all[k + d]) keep[k + d] = true
  })
  const out: DiffLine[] = []
  let skipped = 0
  all.forEach((l, k) => {
    if (keep[k] || all.length <= 12) {
      if (skipped) out.push({ t: ' ', s: `⋯ ${skipped}` })
      skipped = 0
      out.push(l)
    } else skipped++
  })
  if (skipped) out.push({ t: ' ', s: `⋯ ${skipped}` })
  return out
}

export function diffStats(lines: DiffLine[]) {
  let add = 0
  let del = 0
  for (const l of lines) {
    if (l.t === '+') add++
    else if (l.t === '-') del++
  }
  return { add, del }
}

export function fmtTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 10_000) return `${Math.round(n / 1000)}k`
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

export function fmtCost(usd: number): string {
  if (!usd) return '$0'
  if (usd < 0.01) return `$${usd.toFixed(4)}`
  if (usd < 10) return `$${usd.toFixed(2)}`
  return `$${usd.toFixed(1)}`
}

export function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(s < 10 ? 1 : 0)} s`
  const m = Math.floor(s / 60)
  return `${m} min ${Math.round(s % 60)} s`
}

export function fmtElapsed(sec: number): string {
  const s = Math.max(0, Math.floor(sec))
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}:${String(s % 60).padStart(2, '0')}`
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, '0')}`
}

/** Touch layout (live) - see stores/media.ts. */
export { useCompact as useIsMobile } from '@/stores/media'
