// Side question ("Question" in the waiting-messages card): the waiting messages are taken back and asked
// apart - Claude answers about the session from a throwaway copy of its thread while the running turn goes
// on (POST /sessions/{id}/ask, nothing saved). The answer shows in this panel above the composer; × closes it.
import * as React from 'react'
import { create } from 'zustand'
import { createJSONStorage, persist } from 'zustand/middleware'
import { Copy, MessageCircleQuestion, X } from 'lucide-react'
import { api, errorMessage, seg } from '@/lib/api'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { ASIDE_FORGET_EVENT } from '@/lib/drafts'
import { Markdown } from '@/components/ui/markdown'
import { Spinner, Tooltip, toast } from '@/components/ui'

type Aside = { id: number; question: string; answer?: string; error?: string; ms?: number; leaving?: boolean }

/* The side questions live outside the column: another page (Agents...) unmounts it, and the question - already
 * taken out of the queue - and the answer on its way must still be there when the user comes back. Kept for the
 * tab (sessionStorage); one still waiting for its answer when the page reloads is dropped (its request is gone). */
type AsideState = { bySid: Record<string, Aside>; set: (sid: string, a: Aside | null) => void }
const useAsides = create<AsideState>()(
  persist(
    (set) => ({
      bySid: {},
      set: (sid, a) =>
        set((s) => {
          const bySid = { ...s.bySid }
          if (a) bySid[sid] = a
          else delete bySid[sid]
          return { bySid }
        }),
    }),
    {
      name: 'mx-asides',
      storage: createJSONStorage(() => sessionStorage),
      partialize: (s) => ({ bySid: Object.fromEntries(Object.entries(s.bySid).filter(([, a]) => (a.answer || a.error) && !a.leaving)) }),
    },
  ),
)
if (typeof window !== 'undefined')
  window.addEventListener(ASIDE_FORGET_EVENT, (e) => {
    const sid = (e as CustomEvent<string | undefined>).detail
    if (sid === undefined) useAsides.setState({ bySid: {} })
    else if (Object.hasOwn(useAsides.getState().bySid, sid)) useAsides.getState().set(sid, null)
  })
let seq = Date.now()
const patch = (sid: string, id: number, p: Partial<Aside>) => {
  const a = useAsides.getState().bySid[sid]
  if (a && a.id === id) useAsides.getState().set(sid, { ...a, ...p })
}

/** State + actions of the side question of one session column. */
export function useAside(sid: string) {
  const aside = useAsides((s) => s.bySid[sid] ?? null)
  const start = React.useCallback(
    (question: string) => {
      const q = question.trim()
      if (!q) return
      const id = ++seq
      useAsides.getState().set(sid, { id, question: q })
      api
        .post<{ answer: string; cost_usd: number; duration_ms: number }>(`/api/sessions/${seg(sid)}/ask`, { question: q })
        .then((d) => patch(sid, id, { answer: d.answer, ms: d.duration_ms }))
        .catch((e) => patch(sid, id, { error: errorMessage(e) }))
    },
    [sid],
  )
  const close = React.useCallback(() => {
    const a = useAsides.getState().bySid[sid]
    if (!a) return
    patch(sid, a.id, { leaving: true })
    window.setTimeout(() => {
      if (useAsides.getState().bySid[sid]?.leaving) useAsides.getState().set(sid, null)
    }, 120)
  }, [sid])
  return { aside, start, close, pending: !!aside && !aside.answer && !aside.error }
}

export function AsidePanel({ aside, onClose }: { aside: Aside; onClose: () => void }) {
  const t = useT()
  const pending = !aside.answer && !aside.error
  return (
    <div className="mx-auto w-full max-w-(--mx-read,860px) px-3 pb-2">
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
                  className="flex size-7 items-center justify-center rounded-md text-muted-foreground pointer-coarse:size-10 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
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
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground pointer-coarse:size-10 hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
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
