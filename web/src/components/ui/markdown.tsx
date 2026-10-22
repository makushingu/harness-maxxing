import * as React from 'react'
import { Link } from 'react-router'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { createLowlight } from 'lowlight'
import { cn } from '@/lib/utils'
import { CodeBlock } from './code-block'
import { Diagram } from './diagram'
import { withGroups } from '@/i18n'

// ```git blocks: the live graph of a repository (features/git), loaded the first time one shows up.
const GitBlock = React.lazy(withGroups(['git'], () => import('@/features/git/GitBlock')))
const InfraBlock = React.lazy(withGroups(['infra'], () => import('@/features/infra/InfraBlock')))

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
/** A fenced code block with a language somewhere in the text (generous: a false positive only costs a re-render). */
const FENCE_LANG = /(?:`{3,}|~{3,})[ \t]*[^\s`~]/

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
          code.children = ll.highlight(lang, hText(code)).children as unknown as HNode[]
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

export type MarkdownProps = {
  children: string
  className?: string
  /** Rewrite internal links (e.g. docs slugs). Return null to keep the default behaviour. */
  onLink?: (href: string) => (() => void) | null
  /** Extra component overrides. */
  components?: Components
}

/**
 * GitHub-flavoured markdown. Raw HTML is NOT rendered (escaped), unsafe URLs are dropped, app routes (/…) use
 * the router, external links
 * open in a new tab with rel="noopener noreferrer nofollow", code blocks are highlighted with a copy button,
 * ```mermaid blocks are drawn as diagrams, ```git blocks as the live graph of a repository.
 */
export function Markdown({ children, className, onLink, components }: MarkdownProps) {
  // Re-render once the grammars are there - only the messages that have something to highlight (the others would
  // parse their whole text again for the same output).
  React.useSyncExternalStore(subscribeLowlight, FENCE_LANG.test(children) ? lowlightReady : noHighlight)
  const comps = React.useMemo<Components>(
    () => ({
      a({ href = '', children: c, node: _n, ...rest }) {
        if (!SAFE_URL.test(href)) return <span>{c}</span>
        const handler = onLink?.(href)
        if (handler)
          return (
            <a
              href={href}
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
        if (href.startsWith('/') && !href.startsWith('//') && !href.startsWith('/api/'))
          return (
            <Link to={href} {...(rest as object)}>
              {c}
            </Link>
          )
        const external = /^https?:/i.test(href)
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
        return SAFE_URL.test(s) ? <img src={s} alt={alt || ''} loading="lazy" /> : null
      },
      ...components,
    }),
    [onLink, components],
  )
  // Parsing is one blocking pass: a huge text (a 2 MB .md, a giant table) would freeze the page for seconds.
  if (children.length > MAX_MARKDOWN)
    return <pre className={cn('prose-mx font-sans text-sm whitespace-pre-wrap [overflow-wrap:anywhere]', className)}>{children}</pre>
  return (
    <div className={cn('prose-mx', className)}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS} rehypePlugins={REHYPE_PLUGINS} components={comps} skipHtml>
        {children}
      </ReactMarkdown>
    </div>
  )
}

/** Above this size (characters) a text is shown as plain text instead of formatted. */
const MAX_MARKDOWN = 300_000
