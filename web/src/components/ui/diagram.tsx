import * as React from 'react'
import { Code2, Maximize2, Workflow } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { openFileViewer, threadFiles, useFileViewer } from '@/features/files/viewerStore'
import { CodeBlock, CopyButton } from './code-block'

// ```mermaid blocks drawn as diagrams (flowcharts, sequences, states, timelines…). Mermaid is only downloaded
// the first time a diagram shows up; until it renders - or while a streamed block is still incomplete - the
// code is shown. The last good drawing stays on screen while a block is being streamed.
// A click opens the diagram in the file viewer like an image (zoom, fullscreen, ← / → with the thread's files):
// its "path" there is `mx-diagram:<hash>`, the code being kept here.

type Mermaid = typeof import('mermaid').default
let loader: Promise<Mermaid> | null = null
let configured: boolean | null = null
const load = () =>
  (loader ??= import('mermaid')
    .then((m) => m.default)
    .catch((e) => {
      loader = null // a failed download is tried again by the next diagram, not remembered until a reload
      throw e
    }))

export const DIAGRAM_PREFIX = 'mx-diagram:'
const codes = new Map<string, string>()
/** The viewer "path" of a diagram (same code, same path: a re-rendered message keeps its place in ← / →). */
function diagramId(code: string) {
  let h = 5381
  for (let i = 0; i < code.length; i++) h = ((h << 5) + h + code.charCodeAt(i)) | 0
  return DIAGRAM_PREFIX + (h >>> 0).toString(36)
}
/** Keeps the code of a drawn diagram for the viewer (not every partial version of a streamed one); the last 200. */
function remember(id: string, code: string) {
  codes.delete(id)
  codes.set(id, code)
  if (codes.size > 200) codes.delete(codes.keys().next().value!)
}
export const diagramCode = (id: string) => codes.get(id) ?? null
/** Open a diagram (its code) in the file viewer, alone. */
export function showDiagram(code: string) {
  const id = diagramId(code)
  remember(id, code)
  openFileViewer(id)
}

function useDark() {
  const get = () => document.documentElement.classList.contains('dark')
  const [dark, setDark] = React.useState(get)
  React.useEffect(() => {
    const mo = new MutationObserver(() => setDark(get()))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
    return () => mo.disconnect()
  }, [])
  return dark
}

let seq = 0
// Mermaid renders through one shared hidden container: one diagram at a time.
let queue: Promise<unknown> = Promise.resolve()
/** Last drawings (the viewer opens on the one already drawn in the message, no second render). */
const drawn = new Map<string, string>()

const LOADS = 'img,image,feImage,video,audio,source,track,picture,input,object,embed,iframe,link,script'
const REMOTE_CSS = /@import[^;]*;?|url\(\s*(?!['"]?(?:#|data:))[^)]*\)/gi
// Mermaid measures a label in the page: a tag or a style that loads something (`<img src>`, `background:url()`) would
// send its request while the diagram is drawn. `secure`: a diagram cannot change these with its own directives.
const LABELS = {
  dompurifyConfig: { FORBID_TAGS: ['style', ...LOADS.split(',')], FORBID_ATTR: ['style', 'src', 'srcset', 'background', 'poster'] },
  secure: ['secure', 'securityLevel', 'startOnLoad', 'maxTextSize', 'suppressErrorRendering', 'maxEdges', 'dompurifyConfig'],
}

/** An image shape (`@{ img: … }`) is downloaded by mermaid to be measured: such a diagram is not drawn (its code shows). */
async function refuseImages(mermaid: Mermaid, code: string) {
  const diagram = await mermaid.mermaidAPI.getDiagramFromText(code)
  const nodes = (diagram.db as { getData?: () => { nodes?: { img?: unknown }[] } }).getData?.().nodes
  if (Array.isArray(nodes) && nodes.some((n) => n?.img)) throw new Error('image shape')
}

/** Second net, on what mermaid drew: nothing in it loads from elsewhere (a request would carry what its URL says
 *  the moment the message shows). */
export function noRemote(svg: string): string {
  const doc = new DOMParser().parseFromString(svg, 'text/html')
  for (const el of doc.body.querySelectorAll(LOADS)) {
    const src = el.getAttribute('src') ?? el.getAttribute('href') ?? el.getAttribute('xlink:href') ?? ''
    if (!/^(image|feImage|img)$/i.test(el.tagName) || !/^data:image\//i.test(src) || el.hasAttribute('srcset')) el.remove()
  }
  for (const el of doc.body.querySelectorAll('[style]')) {
    const css = el.getAttribute('style') || ''
    if (/url\(|@import/i.test(css)) el.setAttribute('style', css.replace(REMOTE_CSS, 'none'))
  }
  for (const el of doc.body.querySelectorAll('style')) {
    const css = el.textContent || ''
    if (/url\(|@import/i.test(css)) el.textContent = css.replace(REMOTE_CSS, 'none')
  }
  return doc.body.innerHTML
}

async function render(code: string, dark: boolean): Promise<string> {
  const key = `${dark ? 1 : 0}${code}`
  const hit = drawn.get(key)
  if (hit) return hit
  const mermaid = await load()
  if (configured !== dark) {
    // strict: no click handlers or scripts in labels (what could load from elsewhere is removed by noRemote).
    mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', theme: dark ? 'dark' : 'neutral', fontFamily: 'inherit', ...LABELS })
    configured = dark
  }
  await mermaid.parse(code)
  await refuseImages(mermaid, code)
  const svg = noRemote((await mermaid.render(`mx-diagram-${++seq}`, code)).svg)
  if (drawn.size > 50) drawn.delete(drawn.keys().next().value!)
  drawn.set(key, svg)
  return svg
}

/** The SVG of a diagram (null until drawn), redrawn with the theme; `failed` while the code does not parse. */
export function useDiagramSvg(code: string, debounce = 250) {
  const dark = useDark()
  const [svg, setSvg] = React.useState<string | null>(() => drawn.get(`${dark ? 1 : 0}${code}`) ?? null)
  const [failed, setFailed] = React.useState(false)
  React.useEffect(() => {
    let alive = true
    // Debounced: a streamed block changes many times a second.
    const id = setTimeout(() => {
      queue = queue
        .then(() => render(code, dark))
        .then(
          (out) => alive && (setSvg(out), setFailed(false)),
          () => alive && setFailed(true),
        )
    }, debounce)
    return () => {
      alive = false
      clearTimeout(id)
    }
  }, [code, dark, debounce])
  return { svg, failed }
}

/** Open in the viewer: with the files of the conversation around it, or next to the file being viewed. */
function openDiagram(id: string, from: Element) {
  const thread = from.closest('[data-thread]')
  if (thread) return openFileViewer(id, threadFiles(thread))
  const v = useFileViewer.getState()
  if (!v.open) return openFileViewer(id)
  const list = v.list.filter((p) => p !== id)
  const at = Math.min(v.index + 1, list.length)
  v.setList([...list.slice(0, at), id, ...list.slice(at)], at)
}

export function Diagram({ code, className }: { code: string; className?: string }) {
  const t = useT()
  const { svg, failed } = useDiagramSvg(code)
  const [showCode, setShowCode] = React.useState(false)
  const id = React.useMemo(() => diagramId(code), [code])
  React.useEffect(() => {
    if (svg && !failed) remember(id, code)
  }, [svg, failed, id, code])

  if (!svg || showCode)
    return (
      <div className={cn('relative', className)}>
        <CodeBlock code={code} language="mermaid" />
        {svg && (
          <button type="button" onClick={() => setShowCode(false)} className="absolute top-1 right-10 inline-flex h-6 items-center gap-1 rounded-md px-1.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground">
            <Workflow className="size-3.5" /> {t('diagram.show')}
          </button>
        )}
        {!svg && !failed && <span className="absolute top-1.5 right-10 text-[11px] text-muted-foreground">{t('diagram.drawing')}</span>}
      </div>
    )

  return (
    <figure className={cn('group relative min-w-0 overflow-hidden rounded-lg border bg-card', failed && 'opacity-70', className)} data-testid="diagram" data-mx-file={failed ? undefined : id}>
      <button
        type="button"
        onClick={(e) => openDiagram(id, e.currentTarget)}
        aria-label={t('diagram.enlarge')}
        className="mx-diagram flex w-full cursor-zoom-in justify-center overflow-x-auto p-3 outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset [&_svg]:h-auto [&_svg]:max-w-full"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
      <div className="absolute top-1.5 right-1.5 flex items-center gap-0.5 rounded-md bg-popover/90 opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100">
        <button type="button" onClick={(e) => openDiagram(id, e.currentTarget)} aria-label={t('diagram.enlarge')} title={t('diagram.enlarge')} className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
          <Maximize2 className="size-3.5" />
        </button>
        <button type="button" onClick={() => setShowCode(true)} aria-label={t('diagram.code')} title={t('diagram.code')} className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground">
          <Code2 className="size-3.5" />
        </button>
        <CopyButton text={code} />
      </div>
    </figure>
  )
}
