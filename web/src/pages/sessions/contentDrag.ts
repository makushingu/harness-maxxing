// Drag content of one session into another one (Sessions page, mouse): a whole message (its grip), a text selection
// or a file of the thread (thumbnail, chip, file link) dropped on another column lands in that column's composer as a
// quote - the same as the Quote pill and the file menu's Quote. Never sent by itself.
// One delegated `dragstart` on each thread root (no listener per message); the drag state lives here, so only the
// drop overlays re-render. The payload (`application/x-mx-content`) is untrusted: a drop is taken only while a drag
// started in THIS tab is on (its random nonce must match), text is cut and cleaned, a path is only ever written as a
// reference (the server checks paths when a turn uses them). Other drags (columns, tree, OS files) are not touched.
import type * as React from 'react'
import { create } from 'zustand'
import { loadGroups } from '@/i18n'
import { FILE_HREF } from './util'

export const CONTENT_MIME = 'application/x-mx-content'
const MAX_TEXT = 20_000
const MAX_PATH = 4096
/** Per tab, never sent anywhere: a drag started in another tab or site cannot know it. */
const NONCE = Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')

export type Dropped = { kind: 'text'; text: string } | { kind: 'file'; path: string }
type Drag = { from: string }

/** The drag in progress (`from`: session id it started in) and the column under it. */
export const useContentDrag = create<{ drag: Drag | null; over: string | null }>(() => ({ drag: null, over: null }))

/** Text of a message grip (`[data-mx-drag]`), registered by a ref: the delegated handler reads it on dragstart. */
const gripTexts = new WeakMap<Element, string>()
export const gripRef = (text: string) => (el: HTMLElement | null) => void (el && gripTexts.set(el, text))

/** Control characters out (tabs and newlines stay), length capped. */
function cleanText(s: string): string {
  // eslint-disable-next-line no-control-regex
  const t = s.replace(/\r\n?/g, '\n').replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u200e\u200f\u2028-\u202e\u2066-\u2069]/g, '').trim()
  return t.length > MAX_TEXT ? t.slice(0, MAX_TEXT).trimEnd() + '…' : t
}

/** An absolute path, `.` / `..` / repeated slashes resolved; null when it is not one. */
export function cleanPath(p: unknown): string | null {
  // eslint-disable-next-line no-control-regex
  if (typeof p !== 'string' || !p.startsWith('/') || p.length > MAX_PATH || /[\u0000-\u001f\u007f]/.test(p)) return null
  const out: string[] = []
  for (const part of p.split('/')) {
    if (!part || part === '.') continue
    if (part === '..') out.pop()
    else out.push(part)
  }
  return out.length ? '/' + out.join('/') : null
}

/** The file under an element of the thread (data-mx-file, answer links #mx-file=), like the file menu. */
function fileAt(el: Element): string | null {
  const hit = el.closest<HTMLElement>(`[data-mx-file], a[href^="${FILE_HREF}"]`)
  if (!hit) return null
  const raw = hit.dataset.mxFile ?? decodeURIComponent((hit.getAttribute('href') || '').slice(FILE_HREF.length))
  return cleanPath(raw)
}

/** The small chip under the pointer (built with DOM text, never HTML), dropped right after the browser took its picture. */
function dragChip(dt: DataTransfer, icon: string, label: string) {
  const chip = document.createElement('div')
  chip.style.cssText =
    'position:fixed;top:-200px;left:0;display:flex;align-items:center;gap:6px;max-width:240px;padding:4px 10px;border-radius:8px;' +
    'font:500 12px/20px system-ui,sans-serif;background:var(--card,#fff);color:var(--foreground,#111);border:1px solid var(--border,#ddd);' +
    'box-shadow:0 2px 8px rgb(0 0 0/.15);white-space:nowrap;pointer-events:none'
  const i = document.createElement('span')
  i.textContent = icon
  const l = document.createElement('span')
  l.style.cssText = 'overflow:hidden;text-overflow:ellipsis'
  l.textContent = label.length > 40 ? label.slice(0, 40) + '…' : label
  chip.append(i, l)
  document.body.append(chip)
  dt.setDragImage(chip, 12, 14)
  setTimeout(() => chip.remove(), 0)
}

let ended = false

/** Delegated `dragstart` of a thread (session `from`): a message grip, a file, or the selected text. */
export function onThreadDragStart(e: React.DragEvent, from: string | undefined) {
  if (!from) return
  const dt = e.dataTransfer
  const target = e.target as Node
  const el = target instanceof Element ? target : target.parentElement
  const sel = window.getSelection()
  const selected = target.nodeType === Node.TEXT_NODE || (!!el && !!sel && !sel.isCollapsed && sel.containsNode(el, true) && !el.closest('[data-mx-drag], [data-mx-file], a, img'))
  let item: Dropped | null = null
  if (selected) {
    // the selection itself (dragging a selection starts on its text)
    const text = cleanText(sel?.toString() || '')
    if (text) item = { kind: 'text', text }
  } else if (el) {
    const grip = el.closest('[data-mx-drag]')
    const text = grip ? cleanText(gripTexts.get(grip) || '') : ''
    const path = grip ? null : fileAt(el)
    if (text) item = { kind: 'text', text }
    else if (path) item = { kind: 'file', path }
  }
  if (!item) return
  // a selection keeps its HTML for other apps; a message or a file is only what is set here
  if (!selected) dt.clearData()
  dt.setData(CONTENT_MIME, JSON.stringify({ v: 1, ...item, from, nonce: NONCE }))
  dt.setData('text/plain', item.kind === 'file' ? item.path : item.text)
  dt.effectAllowed = 'copy'
  if (item.kind === 'file') dragChip(dt, '📎', item.path.slice(item.path.lastIndexOf('/') + 1))
  else dragChip(dt, '❝', item.text.replace(/\s+/g, ' '))
  void loadGroups(['drag'])
  // after the drag has started (changing the page during dragstart can cancel it) - unless it already ended
  ended = false
  requestAnimationFrame(() => {
    if (ended) return
    useContentDrag.setState({ drag: { from }, over: null })
    // no mouse move while a drag is on: the first one after it means it is over, even when its source left the page
    // (a re-rendered row) and its dragend never reached the thread
    window.addEventListener('mousemove', onThreadDragEnd, { capture: true, once: true })
  })
}

export function onThreadDragEnd() {
  ended = true
  window.removeEventListener('mousemove', onThreadDragEnd, { capture: true })
  useContentDrag.setState({ drag: null, over: null })
}

const isContent = (e: React.DragEvent) => e.dataTransfer.types.includes(CONTENT_MIME)

/** `dragover` on column `col` of session `sid` (null: a new session). True when it was a content drag, handled:
 *  accepted from another session; refused (no drop at all) on its own session. A drag that did not start in this tab
 *  is not handled: the browser does its default (plain text into a text field). */
export function contentDragOver(e: React.DragEvent, col: string, sid: string | null): boolean {
  const { drag, over } = useContentDrag.getState()
  if (!drag || !isContent(e)) return false
  e.preventDefault()
  if (drag.from === sid) {
    e.dataTransfer.dropEffect = 'none'
    return true
  }
  e.dataTransfer.dropEffect = 'copy'
  if (over !== col) useContentDrag.setState({ over: col })
  return true
}

export function contentDragLeave(e: React.DragEvent, col: string) {
  if (useContentDrag.getState().over !== col) return
  // relatedTarget is often null on drag events: then what is under the pointer
  const to = (e.relatedTarget as Node | null) ?? document.elementFromPoint(e.clientX, e.clientY)
  if (!e.currentTarget.contains(to)) useContentDrag.setState({ over: null })
}

/** `drop` on a column: the checked content for its composer, `null` for a content drop with nothing to take (own
 *  session, forged or broken payload), `undefined` when it is not a content drop of this tab. */
export function contentDrop(e: React.DragEvent, sid: string | null): Dropped | null | undefined {
  const { drag } = useContentDrag.getState()
  if (!drag || !isContent(e)) return undefined
  e.preventDefault()
  useContentDrag.setState({ over: null })
  if (drag.from === sid) return null
  return parsePayload(e.dataTransfer.getData(CONTENT_MIME))
}

export function parsePayload(raw: string): Dropped | null {
  let p: unknown
  try {
    p = JSON.parse(raw)
  } catch {
    return null
  }
  if (!p || typeof p !== 'object') return null
  const o = p as Record<string, unknown>
  if (o.v !== 1 || o.nonce !== NONCE || typeof o.from !== 'string') return null
  if (o.kind === 'text' && typeof o.text === 'string') {
    const text = cleanText(o.text)
    return text ? { kind: 'text', text } : null
  }
  if (o.kind === 'file') {
    const path = cleanPath(o.path)
    return path ? { kind: 'file', path } : null
  }
  return null
}
