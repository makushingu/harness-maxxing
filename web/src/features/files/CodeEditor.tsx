// CodeMirror 6 editor / read-only code viewer. Lazy-loaded (its own chunk): import it through
// `LazyCodeEditor` from ./lazy. Languages are loaded on demand per extension.
// The text is never transformed: what you see is the exact file content (byte-identical round trip).
import * as React from 'react'
import { fromHeading, getReadPos, headingAt, setReadPos, sourceHeadings } from './readPos'
import { Compartment, EditorState, type Extension } from '@codemirror/state'
import {
  EditorView,
  crosshairCursor,
  drawSelection,
  dropCursor,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  keymap,
  lineNumbers,
  rectangularSelection,
} from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands'
import { bracketMatching, foldGutter, foldKeymap, indentOnInput, StreamLanguage, syntaxHighlighting } from '@codemirror/language'
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search'
import { closeBrackets, closeBracketsKeymap } from '@codemirror/autocomplete'
import { tagHighlighter, tags as t } from '@lezer/highlight'
import { extOf } from './kinds'

/** Maps lezer tags onto the highlight.js classes themed in globals.css (one palette for the whole app). */
const highlighter = tagHighlighter([
  { tag: [t.keyword, t.controlKeyword, t.operatorKeyword, t.definitionKeyword, t.moduleKeyword, t.modifier, t.bool, t.null, t.self, t.atom], class: 'hljs-keyword' },
  { tag: [t.string, t.special(t.string), t.regexp, t.character, t.attributeValue, t.url, t.inserted], class: 'hljs-string' },
  { tag: [t.number, t.integer, t.float, t.unit, t.special(t.variableName)], class: 'hljs-number' },
  { tag: [t.comment, t.lineComment, t.blockComment, t.docComment, t.quote], class: 'hljs-comment' },
  { tag: [t.function(t.variableName), t.function(t.propertyName), t.className, t.typeName, t.tagName, t.propertyName, t.labelName, t.namespace], class: 'hljs-title' },
  { tag: [t.heading, t.heading1, t.heading2, t.heading3], class: 'hljs-title cm-mx-strong' },
  { tag: [t.meta, t.processingInstruction, t.documentMeta, t.annotation, t.attributeName, t.contentSeparator], class: 'hljs-meta' },
  { tag: [t.deleted, t.invalid], class: 'hljs-deletion' },
  { tag: t.strong, class: 'cm-mx-strong' },
  { tag: t.emphasis, class: 'cm-mx-em' },
  { tag: t.link, class: 'cm-mx-link' },
  { tag: t.monospace, class: 'hljs-string' },
])

const theme = EditorView.theme({
  '&': { height: '100%', fontSize: '12.5px', backgroundColor: 'transparent', color: 'var(--foreground)' },
  '&.cm-focused': { outline: 'none' },
  '.cm-scroller': {
    fontFamily: "var(--mx-font-mono, ui-monospace, 'SFMono-Regular', 'JetBrains Mono', Menlo, Consolas, monospace)",
    lineHeight: '1.6',
    overscrollBehavior: 'contain',
  },
  '.cm-content': { padding: '10px 0', caretColor: 'var(--primary)' },
  '.cm-line': { padding: '0 14px 0 6px' },
  '.cm-gutters': { backgroundColor: 'var(--background)', color: 'color-mix(in oklab, var(--muted-foreground) 70%, transparent)', border: 'none', borderRight: '1px solid var(--border)' },
  '.cm-lineNumbers .cm-gutterElement': { padding: '0 10px 0 14px', minWidth: '2.5em' },
  '.cm-activeLine': { backgroundColor: 'color-mix(in oklab, var(--accent) 45%, transparent)' },
  '.cm-activeLineGutter': { backgroundColor: 'color-mix(in oklab, var(--accent) 45%, transparent)', color: 'var(--foreground)' },
  '.cm-cursor, .cm-dropCursor': { borderLeftColor: 'var(--primary)', borderLeftWidth: '2px' },
  '&.cm-focused > .cm-scroller > .cm-selectionLayer .cm-selectionBackground, .cm-selectionBackground, ::selection': {
    backgroundColor: 'color-mix(in oklab, var(--primary) 28%, transparent) !important',
  },
  '.cm-selectionMatch': { backgroundColor: 'color-mix(in oklab, var(--primary) 14%, transparent)' },
  '.cm-searchMatch': { backgroundColor: 'color-mix(in oklab, var(--warning) 30%, transparent)', outline: '1px solid color-mix(in oklab, var(--warning) 60%, transparent)' },
  '.cm-searchMatch.cm-searchMatch-selected': { backgroundColor: 'color-mix(in oklab, var(--warning) 55%, transparent)' },
  '&.cm-focused .cm-matchingBracket': { backgroundColor: 'color-mix(in oklab, var(--primary) 22%, transparent)', outline: 'none' },
  '.cm-foldPlaceholder': { backgroundColor: 'var(--muted)', border: '1px solid var(--border)', color: 'var(--muted-foreground)', borderRadius: '4px', padding: '0 4px' },
  '.cm-foldGutter .cm-gutterElement': { padding: '0 4px', cursor: 'pointer' },
  '.cm-tooltip': { backgroundColor: 'var(--popover)', color: 'var(--popover-foreground)', border: '1px solid var(--border)', borderRadius: '8px' },
  '.cm-panels': { backgroundColor: 'var(--card)', color: 'var(--foreground)', borderColor: 'var(--border)' },
  '.cm-panels.cm-panels-top': { borderBottom: '1px solid var(--border)' },
  '.cm-panel.cm-search': { padding: '6px 10px', fontFamily: 'inherit', fontSize: '13px' },
  '.cm-panel.cm-search input, .cm-panel.cm-search button': { fontSize: '13px' },
  '.cm-textfield': { backgroundColor: 'var(--background)', border: '1px solid var(--input)', borderRadius: '6px', padding: '2px 6px', color: 'var(--foreground)' },
  '.cm-button': { backgroundImage: 'none', backgroundColor: 'var(--secondary)', color: 'var(--secondary-foreground)', border: '1px solid var(--border)', borderRadius: '6px', padding: '2px 8px' },
  '.cm-panel.cm-search [name=close]': { color: 'var(--muted-foreground)', fontSize: '16px' },
  '.cm-mx-strong': { fontWeight: '650' },
  '.cm-mx-em': { fontStyle: 'italic' },
  '.cm-mx-link': { textDecoration: 'underline', textUnderlineOffset: '3px' },
})

/** Language support by extension (dynamic imports → one small chunk per language). */
async function loadLanguage(filename: string): Promise<Extension | null> {
  const ext = extOf(filename)
  switch (ext) {
    case 'md':
    case 'markdown':
    case 'mdx':
      return (await import('@codemirror/lang-markdown')).markdown()
    case 'py':
      return (await import('@codemirror/lang-python')).python()
    case 'js':
    case 'mjs':
    case 'cjs':
      return (await import('@codemirror/lang-javascript')).javascript()
    case 'jsx':
      return (await import('@codemirror/lang-javascript')).javascript({ jsx: true })
    case 'ts':
    case 'mts':
    case 'cts':
      return (await import('@codemirror/lang-javascript')).javascript({ typescript: true })
    case 'tsx':
      return (await import('@codemirror/lang-javascript')).javascript({ jsx: true, typescript: true })
    case 'json':
    case 'jsonc':
      return (await import('@codemirror/lang-json')).json()
    case 'yaml':
    case 'yml':
      return (await import('@codemirror/lang-yaml')).yaml()
    case 'toml':
      return StreamLanguage.define((await import('@codemirror/legacy-modes/mode/toml')).toml)
    case 'sh':
    case 'bash':
    case 'zsh':
    case 'env':
      return StreamLanguage.define((await import('@codemirror/legacy-modes/mode/shell')).shell)
    case 'css':
    case 'scss':
      return (await import('@codemirror/lang-css')).css()
    case 'html':
    case 'htm':
    case 'vue':
    case 'svelte':
      return (await import('@codemirror/lang-html')).html()
    case 'sql':
      return (await import('@codemirror/lang-sql')).sql()
    default:
      return null
  }
}

export type CodeEditorProps = {
  /** Document. When it changes from outside (reload), the editor content is replaced. */
  value: string
  /** File name (language detection). */
  filename: string
  readOnly?: boolean
  onChange?: (value: string) => void
  /** Ctrl/Cmd+S inside the editor. */
  onSave?: () => void
  /** Soft-wrap long lines (markdown, text). */
  wrap?: boolean
  className?: string
  /** Accessible name. */
  label?: string
  autoFocus?: boolean
  /** Text zoom (1 = 12.5 px); the line at the top stays at the top when it changes. */
  zoom?: number
  /** Remember the reading position under this key (the file path): restored when the text arrives. */
  memory?: string
}

const sizeTheme = (z: number) => EditorView.theme({ '&.cm-editor': { fontSize: `${12.5 * z}px` } })
const isMarkdown = (name: string) => /\.(md|markdown|mdx)$/i.test(name)

export default function CodeEditor({ value, filename, readOnly, onChange, onSave, wrap, className, label, autoFocus, zoom = 1, memory }: CodeEditorProps) {
  const host = React.useRef<HTMLDivElement>(null)
  const view = React.useRef<EditorView | null>(null)
  const cbs = React.useRef({ onChange, onSave })
  cbs.current = { onChange, onSave }
  const comps = React.useRef({ lang: new Compartment(), ro: new Compartment(), wrap: new Compartment(), size: new Compartment() })
  const restored = React.useRef(false)

  /** First line shown at the top of the scroller. */
  const topLine = (v: EditorView) => v.state.doc.lineAt(v.lineBlockAtHeight(v.scrollDOM.getBoundingClientRect().top - v.documentTop).from).number
  const heads = React.useRef<{ doc: unknown; lines: number[] }>({ doc: null, lines: [] })
  const headings = (v: EditorView) => {
    if (!isMarkdown(filename)) return null
    if (heads.current.doc !== v.state.doc) heads.current = { doc: v.state.doc, lines: sourceHeadings(v.state.doc.toString()) }
    return heads.current.lines
  }
  const save = (v: EditorView) => {
    if (!memory || !restored.current) return
    const d = v.scrollDOM
    const line = topLine(v)
    const hs = headings(v)
    setReadPos(memory, { view: 'src', line, frac: d.scrollHeight > d.clientHeight ? d.scrollTop / (d.scrollHeight - d.clientHeight) : 0, h: hs ? headingAt(hs, line, v.state.doc.lines + 1) : undefined })
  }
  const toLine = (v: EditorView, n: number) => {
    const line = v.state.doc.line(Math.max(1, Math.min(v.state.doc.lines, Math.round(n))))
    v.dispatch({ effects: EditorView.scrollIntoView(line.from, { y: 'start' }) })
  }
  /** Back to where the reader was in this file (exact line in the editor, else the same heading, else the same share). */
  const restore = (v: EditorView) => {
    if (restored.current) return
    restored.current = true
    const pos = memory ? getReadPos(memory) : null
    if (!pos) return
    requestAnimationFrame(() => {
      if (view.current !== v) return
      const hs = headings(v)
      const viaHeading = pos.view !== 'src' && pos.h && hs ? fromHeading(hs, pos.h, v.state.doc.lines + 1) : null
      if (pos.view === 'src' && pos.line) toLine(v, pos.line)
      else if (viaHeading != null) toLine(v, viaHeading)
      else if (pos.frac > 0) {
        const d = v.scrollDOM
        d.scrollTop = pos.frac * (d.scrollHeight - d.clientHeight)
      }
    })
  }

  // Create once per mount (the parent keys the editor by path).
  React.useEffect(() => {
    const c = comps.current
    const state = EditorState.create({
      doc: value,
      extensions: [
        lineNumbers(),
        foldGutter({ openText: '▾', closedText: '▸' }),
        highlightActiveLineGutter(),
        highlightSpecialChars(),
        history(),
        drawSelection(),
        dropCursor(),
        EditorState.allowMultipleSelections.of(true),
        indentOnInput(),
        bracketMatching(),
        closeBrackets(),
        rectangularSelection(),
        crosshairCursor(),
        highlightActiveLine(),
        highlightSelectionMatches(),
        syntaxHighlighting(highlighter),
        keymap.of([
          { key: 'Mod-s', preventDefault: true, run: () => (cbs.current.onSave?.(), true) },
          ...closeBracketsKeymap,
          ...defaultKeymap,
          ...searchKeymap,
          ...historyKeymap,
          ...foldKeymap,
          indentWithTab,
        ]),
        theme,
        c.lang.of([]),
        c.ro.of([EditorState.readOnly.of(!!readOnly), EditorView.editable.of(!readOnly)]),
        c.wrap.of(wrap ? EditorView.lineWrapping : []),
        c.size.of(zoom === 1 ? [] : sizeTheme(zoom)),
        EditorView.contentAttributes.of({ 'aria-label': label || filename, spellcheck: 'false', autocorrect: 'off', autocapitalize: 'off' }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) cbs.current.onChange?.(u.state.doc.toString())
        }),
      ],
    })
    const v = new EditorView({ state, parent: host.current! })
    view.current = v
    if (autoFocus && !readOnly) v.focus()
    if (value) restore(v)
    let raf = 0
    const onScroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        save(v)
      })
    }
    v.scrollDOM.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      cancelAnimationFrame(raf)
      v.scrollDOM.removeEventListener('scroll', onScroll)
      v.destroy()
      view.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Language (async; keeps the plain text visible meanwhile — no layout change).
  React.useEffect(() => {
    let live = true
    loadLanguage(filename)
      .then((lang) => {
        if (live && view.current) view.current.dispatch({ effects: comps.current.lang.reconfigure(lang || []) })
      })
      .catch(() => {})
    return () => {
      live = false
    }
  }, [filename])

  React.useEffect(() => {
    view.current?.dispatch({ effects: comps.current.ro.reconfigure([EditorState.readOnly.of(!!readOnly), EditorView.editable.of(!readOnly)]) })
  }, [readOnly])
  React.useEffect(() => {
    view.current?.dispatch({ effects: comps.current.wrap.reconfigure(wrap ? EditorView.lineWrapping : []) })
  }, [wrap])

  // Zoom: the line at the top stays at the top.
  const firstZoom = React.useRef(true)
  React.useEffect(() => {
    const v = view.current
    if (!v) return
    if (firstZoom.current) return void (firstZoom.current = false)
    const line = topLine(v)
    v.dispatch({ effects: comps.current.size.reconfigure(zoom === 1 ? [] : sizeTheme(zoom)) })
    requestAnimationFrame(() => view.current === v && toLine(v, line))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoom])

  // External value change (reload from disk) → replace the document, keep the cursor in range and the scroll.
  React.useEffect(() => {
    const v = view.current
    if (!v) return
    const cur = v.state.doc.toString()
    if (cur === value) return
    const head = Math.min(v.state.selection.main.head, value.length)
    const top = v.scrollDOM.scrollTop
    v.dispatch({ changes: { from: 0, to: cur.length, insert: value }, selection: { anchor: head } })
    if (!cur) restore(v)
    else v.scrollDOM.scrollTop = top
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value])

  return <div ref={host} className={className} data-testid="code-editor" />
}
