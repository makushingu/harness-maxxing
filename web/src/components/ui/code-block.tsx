import * as React from 'react'
import { Check, Copy } from 'lucide-react'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'

export function CopyButton({ text, className, label }: { text: string | (() => string); className?: string; label?: string }) {
  const t = useT()
  const [done, setDone] = React.useState(false)
  const timer = React.useRef<ReturnType<typeof setTimeout>>(undefined)
  React.useEffect(() => () => clearTimeout(timer.current), [])
  return (
    <button
      type="button"
      aria-label={label || t('common.copy')}
      title={label || t('common.copy')}
      onClick={async () => {
        const ok = await copyText(typeof text === 'function' ? text() : text)
        if (ok) {
          setDone(true)
          clearTimeout(timer.current)
          timer.current = setTimeout(() => setDone(false), 1500)
        }
      }}
      className={cn(
        'inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none max-md:size-10 pointer-coarse:size-10',
        className,
      )}
    >
      {done ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
    </button>
  )
}

/** Monospace block with a copy button. `inline` = one-line command style. */
export function CodeBlock({ code, language, className, inline, children }: { code: string; language?: string; className?: string; inline?: boolean; children?: React.ReactNode }) {
  if (inline)
    return (
      <div className={cn('flex min-w-0 items-center gap-2 rounded-md border bg-muted/50 py-1 pr-1 pl-3 font-mono text-[13px]', className)}>
        <span className="min-w-0 flex-1 overflow-x-auto whitespace-nowrap select-all">{code}</span>
        <CopyButton text={code} />
      </div>
    )
  return (
    <div className={cn('group relative min-w-0 overflow-hidden rounded-lg border bg-muted/40', className)}>
      {language && <div className="border-b px-3 py-1.5 font-mono text-[11px] text-muted-foreground uppercase">{language}</div>}
      <CopyButton text={code} className="absolute top-1.5 right-1.5 bg-popover opacity-0 group-hover:opacity-100 focus-visible:opacity-100 max-md:opacity-100 pointer-coarse:opacity-100" />
      <pre className="overflow-x-auto p-3 font-mono text-[12.5px] leading-relaxed">{children ?? <code>{code}</code>}</pre>
    </div>
  )
}
