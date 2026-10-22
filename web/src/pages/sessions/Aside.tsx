// Side question ("Question" in the waiting-messages card): the waiting messages are taken back and asked
// apart - Claude answers about the session from a throwaway copy of its thread while the running turn goes
// on (POST /sessions/{id}/ask, nothing saved). The answer shows in this panel above the composer; × closes it.
import * as React from 'react'
import { Copy, MessageCircleQuestion, X } from 'lucide-react'
import { useAskAside } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { Markdown } from '@/components/ui/markdown'
import { Spinner, Tooltip, toast } from '@/components/ui'

type Aside = { id: number; question: string; answer?: string; error?: string; ms?: number; leaving?: boolean }

/** State + actions of the side question of one session column. */
export function useAside(sid: string) {
  const ask = useAskAside()
  const [aside, setAside] = React.useState<Aside | null>(null)
  const seq = React.useRef(0)
  const start = React.useCallback(
    (question: string) => {
      const q = question.trim()
      if (!q) return
      const id = ++seq.current
      setAside({ id, question: q })
      const done = (patch: Partial<Aside>) => setAside((a) => (a && a.id === id ? { ...a, ...patch } : a))
      ask.mutate({ id: sid, question: q }, { onSuccess: (d) => done({ answer: d.answer, ms: d.duration_ms }), onError: (e) => done({ error: errorMessage(e) }) })
    },
    [sid, ask],
  )
  const close = React.useCallback(() => {
    setAside((a) => (a ? { ...a, leaving: true } : a))
    window.setTimeout(() => setAside((a) => (a?.leaving ? null : a)), 120)
  }, [])
  return { aside, start, close, pending: ask.isPending }
}

export function AsidePanel({ aside, onClose }: { aside: Aside; onClose: () => void }) {
  const t = useT()
  const pending = !aside.answer && !aside.error
  return (
    <div className="mx-auto w-full max-w-[860px] px-3 pb-2">
      <section
        aria-label={t('aside.title')}
        aria-live="polite"
        className={cn('flex max-h-[min(55vh,520px)] flex-col overflow-hidden rounded-xl border bg-card shadow-pop', aside.leaving ? 'animate-out [animation-fill-mode:forwards]' : 'mx-rise')}
      >
        <header className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
          <MessageCircleQuestion className="size-4 shrink-0 text-primary" />
          <span className="text-[13px] font-medium">{t('aside.title')}</span>
          <span className="min-w-0 truncate text-xs text-muted-foreground">{t('aside.subtitle')}</span>
          <span className="ml-auto flex shrink-0 items-center gap-0.5">
            {aside.answer && (
              <Tooltip content={t('common.copy')}>
                <button
                  type="button"
                  aria-label={t('common.copy')}
                  onClick={() => void copyText(aside.answer!).then((ok) => ok && toast.success(t('aside.copied')))}
                  className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                >
                  <Copy className="size-3.5" />
                </button>
              </Tooltip>
            )}
            <Tooltip content={t('aside.close')}>
              <button
                type="button"
                aria-label={t('aside.close')}
                onClick={onClose}
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
              >
                <X className="size-4" />
              </button>
            </Tooltip>
          </span>
        </header>
        <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-3">
          <p className="mb-2 line-clamp-3 text-[13px] whitespace-pre-wrap text-muted-foreground">{aside.question}</p>
          {pending ? (
            <p className="flex items-center gap-2 text-[13px] text-muted-foreground">
              <Spinner className="size-3.5 text-primary" /> {t('aside.pending')}
            </p>
          ) : aside.error ? (
            <p role="alert" className="text-[13px] text-destructive">
              {aside.error}
            </p>
          ) : (
            <Markdown className="mx-assistant text-[14px]">{aside.answer!}</Markdown>
          )}
        </div>
        {aside.ms !== undefined && <footer className="shrink-0 border-t px-3 py-1 text-[11px] text-muted-foreground tabular-nums">{t('aside.meta', { s: Math.max(1, Math.round(aside.ms / 1000)) })}</footer>}
      </section>
    </div>
  )
}
