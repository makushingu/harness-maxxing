// Jarvis (/jarvis, Settings -> Features -> Jarvis): one assistant to talk to, who runs Harness for the owner.
// Its conversation is a session of its hidden topic (server jarvis.py), shown with the same column as the Sessions
// page (SessionColumn, "solo"); beside it, the work board: what Jarvis handed to which session, and where it stands.
// Its settings (rights, ask first, daily conversation, brief and night pass times, internals) sit in the gear menu.
import * as React from 'react'
import { Link } from 'react-router'
import { Archive, CalendarDays, Check, ExternalLink, Eye, Hand, ListTodo, MessageSquarePlus, MessagesSquare, Minimize2, Moon, PanelRightClose, Send, Settings2, ShieldCheck, Sparkles, Sun, X, type LucideIcon } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { useCloseJarvisWork, useJarvis, useJarvisBrief, useJarvisDream, useJarvisSettings, useNewJarvisConversation, useOpenJarvis } from '@/lib/queries'
import type { JarvisSettings, JarvisWork } from '@/lib/types'
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { Button, EmptyState, Input, Select, Skeleton, StatusDot, Tooltip } from '@/components/ui'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { ResizeEdge } from '@/components/shell/ResizeEdge'
import { PageHeader } from '@/components/shell/Page'
import { useTelegram } from '@/lib/queries/telegram'
import { SessionColumn } from '@/pages/sessions/Column'
import type { Col } from '@/pages/sessions/store'
import { PreviewProvider } from '@/pages/sessions/FilePreview'
import { sessionsUrl } from '@/pages/sessions/util'
import { Toggle } from '@/pages/sessions/SessionOptions'

/** File links of its conversation open the file viewer, as in a session (the provider the Sessions page has). */
export default function JarvisPage() {
  return (
    <PreviewProvider>
      <JarvisView />
    </PreviewProvider>
  )
}

function JarvisView() {
  const t = useT()
  const { data: st, isLoading } = useJarvis()
  const open = useOpenJarvis()
  const fresh = useNewJarvisConversation()
  const [board, setBoard] = React.useState(false) // phone / tablet: the Work list in place of the conversation
  const [workOpen, setWorkOpen] = React.useState(() => localStorage.getItem(WORK_OPEN_KEY) !== '0') // desktop
  const [workW, setWorkW] = React.useState(() => fitWorkW(Number(localStorage.getItem(WORK_W_KEY))))
  const [settingsOpen, setSettingsOpen] = React.useState(false)
  const aside = React.useRef<HTMLElement>(null)
  const toggleWork = () => {
    if (window.matchMedia('(min-width: 1024px)').matches) {
      const v = !workOpen
      setWorkOpen(v)
      localStorage.setItem(WORK_OPEN_KEY, v ? '1' : '0')
    } else setBoard((b) => !b)
  }
  const saveWorkW = (w: number | null) => {
    const v = w == null ? WORK_W.def : fitWorkW(Math.round(w))
    setWorkW(v)
    if (w == null) localStorage.removeItem(WORK_W_KEY)
    else localStorage.setItem(WORK_W_KEY, String(v))
  }
  const sid = st?.session?.id || ''
  // the first visit (or the conversation was removed): its conversation is made now
  const opening = open.isPending
  const openMutate = open.mutate
  React.useEffect(() => {
    if (st?.on && !st.session && !opening && !open.isError) openMutate()
  }, [st?.on, st?.session, opening, open.isError, openMutate])
  const col = React.useMemo<Col>(() => ({ key: `jarvis:${sid}`, kind: 'session', id: sid }), [sid])

  if (isLoading) return <Skeleton className="m-6 h-40" />
  if (!st?.on)
    return (
      <div className="flex flex-1 items-center justify-center p-6">
        <EmptyState
          icon={Sparkles}
          title={t('jarvis.off.title')}
          description={t('jarvis.off.desc')}
          action={
            <Button asChild>
              <Link to="/settings/features">{t('jarvis.off.action')}</Link>
            </Button>
          }
        />
      </div>
    )
  const waiting = st.asks
  return (
    <div className="flex h-full min-h-0 flex-1 flex-col" data-testid="jarvis-page">
      <PageHeader
        leading={
          <span className="flex size-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <Sparkles className="size-[18px]" />
          </span>
        }
        title="Jarvis"
        description={
          st.open
            ? t(waiting ? 'jarvis.header.workAsks' : 'jarvis.header.work', { count: st.open, asks: waiting })
            : t('jarvis.header.idle')
        }
        actions={
          <div className="flex items-center gap-1">
            <Tooltip content={t('jarvis.board.title')}>
              <Button
                variant={board ? 'secondary' : 'ghost'}
                size="icon-sm"
                className={cn(workOpen && 'lg:bg-secondary')}
                aria-label={t('jarvis.board.title')}
                aria-pressed={board || undefined}
                onClick={toggleWork}
                data-testid="jarvis-work-toggle"
              >
                <ListTodo />
              </Button>
            </Tooltip>
            <Tooltip content={t('jarvis.set.title')}>
              <Button variant="ghost" size="icon-sm" aria-label={t('jarvis.set.title')} aria-haspopup="dialog" onClick={() => setSettingsOpen(true)} data-testid="jarvis-settings">
                <Settings2 />
              </Button>
            </Tooltip>
            <JarvisSettingsDialog open={settingsOpen} onOpenChange={setSettingsOpen} settings={st.settings} onNew={() => fresh.mutate()} renewing={fresh.isPending} />
          </div>
        }
      />
      <div className="flex min-h-0 flex-1" style={{ '--safe-top': '0px' } as React.CSSProperties}>
        <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', board && 'max-lg:hidden')}>
          {sid ? <SessionColumn key={sid} col={col} sid={sid} index={0} count={1} variant="solo" own ownPlaceholder={t('jarvis.placeholder')} /> : <Skeleton className="m-6 h-40" />}
        </div>
        <aside
          ref={aside}
          className={cn('relative flex min-h-0 shrink-0 flex-col border-l max-lg:!w-full max-lg:border-l-0', !board && 'max-lg:hidden', !workOpen && 'lg:hidden')}
          style={{ width: workW }}
          data-testid="jarvis-board"
        >
          <ResizeEdge side={aside} edge="left" min={WORK_W.min} max={WORK_W.max} onWidth={saveWorkW} className="max-lg:hidden" />
          <Board work={st.work} onHide={toggleWork} />
        </aside>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- the work board */
type Group = { key: string; title: TKey; items: JarvisWork[] }

function Board({ work, onHide }: { work: JarvisWork[]; onHide: () => void }) {
  const t = useT()
  const [closed, setClosed] = React.useState(false)
  const groups: Group[] = [
    { key: 'asks', title: 'jarvis.board.asks', items: work.filter((w) => w.state === 'replied' && w.question) },
    { key: 'running', title: 'jarvis.board.running', items: work.filter((w) => w.state === 'running') },
    { key: 'done', title: 'jarvis.board.done', items: work.filter((w) => (w.state === 'replied' && !w.question) || w.state === 'failed') },
  ]
  const old = work.filter((w) => w.state === 'closed')
  const empty = groups.every((g) => !g.items.length)
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-11 shrink-0 items-center gap-2 border-b pr-2 pl-4">
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{t('jarvis.board.title')}</span>
        {old.length > 0 && (
          <button type="button" className="shrink-0 text-xs text-muted-foreground hover:text-foreground" onClick={() => setClosed((c) => !c)}>
            {t(closed ? 'jarvis.board.hideClosed' : 'jarvis.board.showClosed', { count: old.length })}
          </button>
        )}
        <Tooltip content={t('jarvis.board.hide')}>
          <Button variant="ghost" size="icon-sm" aria-label={t('jarvis.board.hide')} onClick={onHide} data-testid="jarvis-work-hide">
            <PanelRightClose className="max-lg:hidden" />
            <X className="lg:hidden" />
          </Button>
        </Tooltip>
      </div>
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto p-3">
        {empty && !closed && <p className="px-1 py-6 text-center text-[13px] text-muted-foreground">{t('jarvis.board.empty')}</p>}
        {groups
          .filter((g) => g.items.length)
          .map((g) => (
            <section key={g.key} className="space-y-2">
              <h3 className="px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                {t(g.title)} · {g.items.length}
              </h3>
              {g.items.map((w) => (
                <WorkCard key={w.id} w={w} />
              ))}
            </section>
          ))}
        {closed && old.length > 0 && (
          <section className="space-y-2">
            <h3 className="px-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">{t('jarvis.board.closed')}</h3>
            {old.map((w) => (
              <WorkCard key={w.id} w={w} />
            ))}
          </section>
        )}
      </div>
    </div>
  )
}

const TONE = { running: 'running', replied: 'ok', failed: 'error', closed: 'idle' } as const
const STATE_LABEL: Record<JarvisWork['state'], TKey> = {
  running: 'jarvis.state.running',
  replied: 'jarvis.state.replied',
  failed: 'jarvis.state.failed',
  closed: 'jarvis.state.closed',
}

function WorkCard({ w }: { w: JarvisWork }) {
  const t = useT()
  const lang = useLang()
  const close = useCloseJarvisWork()
  const where = w.path.replace(/^projects\//, '').replace('/topics/', '/').replace('/agents/', ' · ')
  const asks = w.state === 'replied' && w.question
  return (
    <article className={cn('rounded-lg border bg-card p-3 text-sm', asks && 'border-warning/50', w.state === 'closed' && 'opacity-60')} data-testid="jarvis-work">
      <div className="flex items-start gap-2">
        <StatusDot tone={asks ? 'warn' : TONE[w.state]} pulse={w.state === 'running'} className="mt-1.5" label={t(STATE_LABEL[w.state])} />
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">
            <span className="text-muted-foreground">#{w.id}</span> {w.title || where}
          </p>
          <p className="truncate text-xs text-muted-foreground">
            {where} · {asks ? t('jarvis.state.asks') : t(STATE_LABEL[w.state])}
            {w.archived && ` · ${t('jarvis.work.archived')}`} · {fmtRelative(w.updated, lang)}
          </p>
        </div>
      </div>
      {w.fresh && (
        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground" data-testid="jarvis-work-fresh">
          {t('jarvis.work.fresh')} {w.fresh}
        </p>
      )}
      {w.result && w.state !== 'running' && <p className="mt-2 line-clamp-3 whitespace-pre-line text-[13px] text-muted-foreground">{w.result}</p>}
      <div className="mt-2 flex items-center justify-end gap-1">
        <Button asChild variant="ghost" size="sm">
          <Link to={sessionsUrl({ id: w.session, path: w.path })}>
            <ExternalLink />
            {t('jarvis.work.open')}
          </Link>
        </Button>
        {w.state !== 'closed' && (
          <Button variant="ghost" size="sm" onClick={() => close.mutate(w.id)} disabled={close.isPending}>
            <Check />
            {t('jarvis.work.close')}
          </Button>
        )}
      </div>
    </article>
  )
}

/* ---------------------------------------------------------------- its settings */
/** Its compaction threshold (server jarvis.COMPACT_CHOICES; 0 = the server's, as every session). */
const COMPACT_AT = [100_000, 150_000, 200_000, 300_000, 0]
/** The Work panel on a wide screen: shown or not, and its width (dragged on its left edge), kept in this browser. */
const WORK_OPEN_KEY = 'mx.jarvis.workOpen'
const WORK_W_KEY = 'mx.jarvis.workWidth'
const WORK_W = { min: 260, def: 320, max: 640 }
/** A saved width within the limits (an old or hand-edited value never squeezes the conversation). */
const fitWorkW = (n: number) => (Number.isFinite(n) && n > 0 ? Math.max(WORK_W.min, Math.min(WORK_W.max, n)) : WORK_W.def)

/** Its settings: a window like a session's options (a sheet from the bottom on a phone, centered on a computer). */
function JarvisSettingsDialog({ open, onOpenChange, settings, onNew, renewing }: { open: boolean; onOpenChange: (v: boolean) => void; settings: JarvisSettings; onNew: () => void; renewing: boolean }) {
  const t = useT()
  const save = useJarvisSettings()
  const brief = useJarvisBrief()
  const dream = useJarvisDream()
  const { data: tg } = useTelegram()
  const set = (k: keyof JarvisSettings, v: boolean | string | number) => save.mutate({ [k]: v })
  const toggles: { k: 'root' | 'ask_first' | 'reuse' | 'archive_done' | 'daily' | 'internals'; icon: LucideIcon; label: TKey; hint: TKey }[] = [
    { k: 'root', icon: ShieldCheck, label: 'jarvis.set.root', hint: 'jarvis.set.rootHint' },
    { k: 'ask_first', icon: Hand, label: 'jarvis.set.ask', hint: 'jarvis.set.askHint' },
    { k: 'reuse', icon: MessagesSquare, label: 'jarvis.set.reuse', hint: 'jarvis.set.reuseHint' },
    { k: 'archive_done', icon: Archive, label: 'jarvis.set.archive', hint: 'jarvis.set.archiveHint' },
    { k: 'daily', icon: CalendarDays, label: 'jarvis.set.daily', hint: 'jarvis.set.dailyHint' },
    { k: 'internals', icon: Eye, label: 'jarvis.set.internals', hint: 'jarvis.set.internalsHint' },
  ]
  const run = (f: () => void) => () => {
    onOpenChange(false)
    f()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-0 p-0 md:max-w-md" data-testid="jarvis-settings-dialog">
        <div className="px-5 pt-5 pb-3 max-md:pt-1">
          <DialogTitle>{t('jarvis.set.title')}</DialogTitle>
          <DialogDescription className="text-xs">{t('jarvis.set.cost')}</DialogDescription>
        </div>

        <div className="border-t px-2 py-2">
          {toggles.map((x) => (
            <Toggle key={x.k} icon={x.icon} label={t(x.label)} hint={t(x.hint)} checked={settings[x.k]} onChange={(v) => set(x.k, v)} />
          ))}
        </div>

        <div className="grid grid-cols-2 gap-3 border-t px-5 py-3">
          <TimeField icon={Sun} label={t('jarvis.set.brief')} value={settings.brief} onSave={(v) => set('brief', v)} />
          <TimeField icon={Moon} label={t('jarvis.set.dream')} value={settings.dream} onSave={(v) => set('dream', v)} />
        </div>

        <div className="space-y-3 border-t px-5 py-3">
          <label className="grid gap-1">
            <span className="flex items-center gap-2 text-sm">
              <Send className="size-4 text-muted-foreground" />
              {t('jarvis.set.telegram')}
            </span>
            <Select
              value={settings.telegram || 'important'}
              onValueChange={(v) => set('telegram', v)}
              options={(['important', 'all', 'off'] as const).map((v) => ({ value: v, label: t(`jarvis.set.telegram.${v}`) }))}
              data-testid="jarvis-telegram"
            />
            <span className="text-xs text-muted-foreground">
              {tg && !tg.chat ? (
                <Link to="/settings/telegram" className="underline underline-offset-2" onClick={() => onOpenChange(false)}>
                  {t('jarvis.set.telegramOff')}
                </Link>
              ) : (
                t('jarvis.set.telegramHint')
              )}
            </span>
          </label>
          <label className="grid gap-1">
            <span className="flex items-center gap-2 text-sm">
              <Minimize2 className="size-4 text-muted-foreground" />
              {t('jarvis.set.compact')}
            </span>
            <Select
              value={String(settings.compact_tokens ?? 0)}
              onValueChange={(v) => set('compact_tokens', Number(v))}
              options={COMPACT_AT.map((n) => ({ value: String(n), label: n ? `${n / 1000}k` : t('jarvis.set.compactSame') }))}
              data-testid="jarvis-compact"
            />
            <span className="text-xs text-muted-foreground">{t('jarvis.set.compactHint')}</span>
          </label>
        </div>

        <div className="border-t px-2 py-2">
          <ActionRow icon={MessageSquarePlus} label={t('jarvis.new')} hint={t('jarvis.new.hint')} disabled={renewing} onClick={run(onNew)} testId="jarvis-new" />
          <ActionRow icon={Sun} label={t('jarvis.set.briefNow')} disabled={brief.isPending} onClick={run(() => brief.mutate())} />
          <ActionRow icon={Moon} label={t('jarvis.set.dreamNow')} disabled={dream.isPending} onClick={run(() => dream.mutate())} />
        </div>
      </DialogContent>
    </Dialog>
  )
}

function ActionRow({ icon: Icon, label, hint, disabled, onClick, testId }: { icon: LucideIcon; label: string; hint?: string; disabled?: boolean; onClick: () => void; testId?: string }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      data-testid={testId}
      className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left outline-none hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 pointer-coarse:py-2.5"
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <span className="min-w-0 flex-1">
        <span className="block text-sm">{label}</span>
        {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
      </span>
    </button>
  )
}

function TimeField({ icon: Icon, label, value, onSave }: { icon: typeof Sun; label: string; value: string; onSave: (v: string) => void }) {
  const t = useT()
  const [v, setV] = React.useState(value)
  React.useEffect(() => setV(value), [value])
  // saved as soon as the time is complete (a short pause), and when the window closes before that: never lost
  const pending = React.useRef<string | null>(null)
  const saveRef = React.useRef(onSave)
  saveRef.current = onSave
  React.useEffect(() => {
    if (v === value || !/^\d\d:\d\d$/.test(v)) return
    pending.current = v
    const id = window.setTimeout(() => {
      pending.current = null
      saveRef.current(v)
    }, 500)
    return () => window.clearTimeout(id)
  }, [v, value])
  React.useEffect(
    () => () => {
      if (pending.current) saveRef.current(pending.current)
    },
    [],
  )
  return (
    <label className="grid gap-1 text-xs text-muted-foreground">
      <span className="flex items-center gap-1">
        <Icon className="size-3.5" />
        {label}
      </span>
      <div className="flex items-center gap-1">
        <Input type="time" value={v} onChange={(e) => setV(e.target.value)} className="h-8" />
        {v && (
          <Tooltip content={t('jarvis.set.none')}>
            <Button variant="ghost" size="icon-sm" aria-label={t('jarvis.set.none')} onClick={() => onSave('')}>
              <X />
            </Button>
          </Tooltip>
        )}
      </div>
    </label>
  )
}
