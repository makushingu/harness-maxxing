// File-type detection and POSIX path helpers shared by the Files page and FilePreview.
import {
  File,
  FileArchive,
  FileAudio,
  FileCode,
  FileImage,
  FileJson,
  FileSpreadsheet,
  FileText,
  FileType,
  FileVideo,
  Folder,
  type LucideIcon,
} from 'lucide-react'

export type FileKind =
  | 'image'
  | 'video'
  | 'audio'
  | 'pdf'
  | 'markdown'
  | 'csv'
  | 'html'
  | 'code'
  | 'text'
  | 'font'
  | 'archive'
  | 'other'
  | 'binary'

const IMAGE = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg', 'avif', 'ico', 'tif', 'tiff', 'heic', 'heif'])
/** Images the browser cannot show: the server converts them (the viewer never loads the original). */
export const CONVERTED_IMAGE = new Set(['tif', 'tiff', 'heic', 'heif'])
const FONT = new Set(['woff', 'woff2', 'ttf', 'otf'])
const CSV = new Set(['csv', 'tsv'])
const HTML = new Set(['html', 'htm'])
/** Archives the server can list (zip, tar and gzip); 7z / rar / zst are only downloadable. */
const LISTABLE = /\.(zip|tar|tgz|tbz2?|txz|gz|bz2|xz)$/i
const VIDEO = new Set(['mp4', 'webm', 'mov', 'm4v', 'ogv', 'mkv'])
const AUDIO = new Set(['mp3', 'wav', 'ogg', 'oga', 'm4a', 'aac', 'flac', 'opus'])
const MARKDOWN = new Set(['md', 'markdown', 'mdx'])
const ARCHIVE = new Set(['zip', 'gz', 'tgz', 'tar', 'bz2', 'xz', '7z', 'rar', 'zst'])
const CODE = new Set([
  'py', 'js', 'mjs', 'cjs', 'jsx', 'ts', 'mts', 'cts', 'tsx', 'json', 'jsonc', 'yaml', 'yml', 'toml', 'sh', 'bash', 'zsh',
  'css', 'scss', 'xml', 'sql', 'go', 'rs', 'rb', 'php', 'java', 'kt', 'c', 'h', 'cpp', 'hpp', 'cs', 'swift',
  'lua', 'ini', 'cfg', 'conf', 'env', 'dockerfile', 'makefile', 'vue', 'svelte',
])
/** Known binary formats: shown as an info card without trying to read them as text. */
const BINARY = new Set([
  'bin', 'exe', 'dll', 'so', 'o', 'a', 'dylib', 'class', 'jar', 'pyc', 'wasm', 'eot',
  'sqlite', 'sqlite3', 'db', 'iso', 'dmg', 'img', 'deb', 'rpm', 'apk', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
  'odt', 'ods', 'odp', 'psd', 'ai', 'sketch', 'fig', 'blend', 'mid', 'pkl', 'npy', 'parquet',
])
const TEXT = new Set(['txt', 'log', 'lock', 'gitignore', 'service', 'timer', 'rst', 'org'])
const TEXT_NAMES = new Set(['dockerfile', 'makefile', 'license', 'readme', 'caddyfile', 'procfile', '.env', '.gitignore', '.bashrc', '.profile'])

export function extOf(name: string): string {
  const base = basename(name).toLowerCase()
  const i = base.lastIndexOf('.')
  return i > 0 ? base.slice(i + 1) : i === 0 ? base.slice(1) : ''
}

/** Best guess from the name (and mime when known). `binary` = unknown: try reading it as text first. */
export function kindOf(name: string, mime?: string): FileKind {
  const ext = extOf(name)
  if (IMAGE.has(ext)) return 'image'
  if (VIDEO.has(ext)) return 'video'
  if (AUDIO.has(ext)) return 'audio'
  if (ext === 'pdf') return 'pdf'
  if (MARKDOWN.has(ext)) return 'markdown'
  if (CSV.has(ext)) return 'csv'
  if (HTML.has(ext)) return 'html'
  if (CODE.has(ext)) return 'code'
  if (TEXT.has(ext) || TEXT_NAMES.has(basename(name).toLowerCase())) return 'text'
  if (FONT.has(ext)) return 'font'
  if (ARCHIVE.has(ext)) return LISTABLE.test(name) ? 'archive' : 'other'
  if (BINARY.has(ext)) return 'other'
  if (mime) {
    if (mime.startsWith('image/')) return 'image'
    if (mime.startsWith('video/')) return 'video'
    if (mime.startsWith('audio/')) return 'audio'
    if (mime.startsWith('text/') || /json|xml|javascript|yaml|toml/.test(mime)) return 'text'
  }
  return 'binary'
}

/** Kinds whose content is fetched with /api/files/read (text). `binary` is attempted too (415 → info card). */
export const isTextual = (k: FileKind) => k === 'markdown' || k === 'csv' || k === 'html' || k === 'code' || k === 'text' || k === 'binary'
/** Text kinds with a rendered view next to their source (markdown, table, web page). */
export const isRendered = (k: FileKind) => k === 'markdown' || k === 'csv' || k === 'html'
/** Kinds with a server thumbnail. */
export const hasThumb = (name: string) => {
  const ext = extOf(name)
  return (IMAGE.has(ext) && ext !== 'svg' && ext !== 'ico') || VIDEO.has(ext) || ext === 'pdf'
}

export function iconFor(type: 'file' | 'dir', name: string): LucideIcon {
  if (type === 'dir') return Folder
  const ext = extOf(name)
  if (ext === 'json' || ext === 'jsonc') return FileJson
  if (ext === 'csv' || ext === 'tsv' || ext === 'xlsx' || ext === 'ods') return FileSpreadsheet
  switch (kindOf(name)) {
    case 'image':
      return FileImage
    case 'video':
      return FileVideo
    case 'audio':
      return FileAudio
    case 'archive':
      return FileArchive
    case 'other':
      return ARCHIVE.has(ext) ? FileArchive : File
    case 'font':
      return FileType
    case 'csv':
      return FileSpreadsheet
    case 'html':
      return FileCode
    case 'code':
      return FileCode
    case 'markdown':
    case 'text':
    case 'pdf':
      return FileText
    default:
      return File
  }
}

/** Tailwind text colour per type (tokens only — subtle hints, not brand colours). */
export const iconTone = (type: 'file' | 'dir') => (type === 'dir' ? 'text-primary' : 'text-muted-foreground')

/* ------------------------------------------------------------------ paths (POSIX, absolute) */
export function basename(p: string): string {
  const s = p.replace(/\/+$/, '')
  const i = s.lastIndexOf('/')
  return i >= 0 ? s.slice(i + 1) : s
}
export function dirname(p: string): string {
  const s = p.replace(/\/+$/, '')
  const i = s.lastIndexOf('/')
  return i > 0 ? s.slice(0, i) : '/'
}
export function joinPath(dir: string, name: string): string {
  return (dir.endsWith('/') ? dir : dir + '/') + name.replace(/^\/+/, '')
}
/** Resolve `input` (absolute, or relative to `dir`, may contain `..`) to a normalised absolute path. */
export function resolvePath(dir: string, input: string): string {
  const raw = input.startsWith('/') ? input : joinPath(dir, input)
  const out: string[] = []
  for (const part of raw.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') out.pop()
    else out.push(part)
  }
  return '/' + out.join('/')
}
export function isInside(path: string, root: string): boolean {
  const r = root.replace(/\/+$/, '')
  return path === r || path.startsWith(r + '/') || r === ''
}
/** Breadcrumb segments from `root` to `path` (inclusive). */
export function crumbs(path: string, root: string): { name: string; path: string }[] {
  const r = root.replace(/\/+$/, '') || '/'
  const out = [{ name: basename(r) || '/', path: r }]
  if (!isInside(path, r) || path === r) return out
  const rest = path.slice(r === '/' ? 1 : r.length + 1).split('/').filter(Boolean)
  let cur = r
  for (const s of rest) {
    cur = joinPath(cur, s)
    out.push({ name: s, path: cur })
  }
  return out
}
/** "notes.md" → "notes (2).md" until `taken` says no. */
export function uniqueName(name: string, taken: (n: string) => boolean, tag = ''): string {
  const i = name.lastIndexOf('.')
  const stem = i > 0 ? name.slice(0, i) : name
  const ext = i > 0 ? name.slice(i) : ''
  let n = tag ? `${stem} (${tag})${ext}` : name
  for (let k = 2; taken(n); k++) n = tag ? `${stem} (${tag} ${k})${ext}` : `${stem} (${k})${ext}`
  return n
}
