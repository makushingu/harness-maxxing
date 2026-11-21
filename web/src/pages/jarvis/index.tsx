// Jarvis (/jarvis, Settings -> Features -> Jarvis): one assistant to talk to, who runs Harness for the owner.
// Its conversation is a session of its hidden topic (server jarvis.py), shown with the same column as the Sessions
// page (SessionColumn, "solo"); beside it, the work board: what Jarvis handed to which session, and where it stands.
// Its settings (rights, ask first, daily conversation, brief and night pass times, internals) sit in the gear menu.
import * as React from 'react'
import { Link } from 'react-router'
import { Check, ExternalLink, ListTodo, MessageSquarePlus, Moon, Settings2, Sparkles, Sun, X } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { useCloseJarvisWork, useJarvis, useJarvisBrief, useJarvisDream, useJarvisSettings, useNewJarvisConversation, useOpenJarvis } from '@/lib/queries'
import type { JarvisSettings, JarvisWork } from '@/lib/types'
import { cn } from '@/lib/utils'
import { fmtRelative } from '@/lib/format'
import { Button, EmptyState, Input, Popover, PopoverContent, PopoverTrigger, Select, Skeleton, StatusDot, Switch, Tooltip } from '@/components/ui'
import { PageHeader } from '@/components/shell/Page'
import { useTelegram } from '@/lib/queries/telegram'
import { SessionColumn } from '@/pages/sessions/Column'
import type { Col } from '@/pages/sessions/store'
import { sessionsUrl } from '@/pages/sessions/util'

export default function JarvisPage() {
  const t = useT()
  const { data: st, isLoading } = useJarvis()
  const open = useOpenJarvis()
  const fresh = useNewJarvisConversation()
  const [board, setBoard] = React.useState(false)
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
              <Button variant={board ? 'secondary' : 'ghost'} size="icon-sm" className="lg:hidden" aria-label={t('jarvis.board.title')} onClick={() => setBoard((b) => !b)}>
                <ListTodo />
              </Button>
            </Tooltip>
            <SettingsMenu settings={st.settings} onNew={() => fresh.mutate()} renewing={fresh.isPending} />
          </div>
        }
      />
      <div className="flex min-h-0 flex-1" style={{ '--safe-top': '0px' } as React.CSSProperties}>
        <div className={cn('flex min-h-0 min-w-0 flex-1 flex-col', board && 'max-lg:hidden')}>
          {sid ? <SessionColumn key={sid} col={col} sid={sid} index={0} count={1} variant="solo" own /> : <Skeleton className="m-6 h-40" />}
        </div>
        <aside className={cn('flex min-h-0 w-80 shrink-0 flex-col border-l max-lg:w-full max-lg:border-l-0', !board && 'max-lg:hidden')} data-testid="jarvis-board">
          <Board work={st.work} />
        </aside>
      </div>
    </div>
  )
}

/* ---------------------------------------------------------------- the work board */
type Group = { key: string; title: TKey; items: JarvisWork[] }

function Board({ work }: { work: JarvisWork[] }) {
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
      <div className="flex h-11 shrink-0 items-center justify-between border-b px-4">
        <span className="text-sm font-medium">{t('jarvis.board.title')}</span>
        {old.length > 0 && (
          <button type="button" className="text-xs text-muted-foreground hover:text-foreground" onClick={() => setClosed((c) => !c)}>
            {t(closed ? 'jarvis.board.hideClosed' : 'jarvis.board.showClosed', { count: old.length })}
          </button>
        )}
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
            {where} · {asks ? t('jarvis.state.asks') : t(STATE_LABEL[w.state])} · {fmtRelative(w.updated, lang)}
          </p>
        </div>
      </div>
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

function SettingsMenu({ settings, onNew, renewing }: { settings: JarvisSettings; onNew: () => void; renewing: boolean }) {
  const t = useT()
  const save = useJarvisSettings()
  const brief = useJarvisBrief()
  const dream = useJarvisDream()
  const { data: tg } = useTelegram()
  const set = (k: keyof JarvisSettings, v: boolean | string | number) => save.mutate({ [k]: v })
  const toggles: { k: 'root' | 'ask_first' | 'daily' | 'internals'; label: TKey; hint: TKey }[] = [
    { k: 'root', label: 'jarvis.set.root', hint: 'jarvis.set.rootHint' },
    { k: 'ask_first', label: 'jarvis.set.ask', hint: 'jarvis.set.askHint' },
    { k: 'daily', label: 'jarvis.set.daily', hint: 'jarvis.set.dailyHint' },
    { k: 'internals', label: 'jarvis.set.internals', hint: 'jarvis.set.internalsHint' },
  ]
  return (
    <Popover>
      <Tooltip content={t('jarvis.set.title')}>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('jarvis.set.title')} data-testid="jarvis-settings">
            <Settings2 />
          </Button>
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent align="end" className="w-80 space-y-4 p-4">
        <p className="text-sm font-medium">{t('jarvis.set.title')}</p>
        {toggles.map((x) => (
          <div key={x.k} className="flex items-start gap-3">
            <div className="min-w-0 flex-1">
              <label htmlFor={`jv-${x.k}`} className="text-sm">
                {t(x.label)}
              </label>
              <p className="text-xs text-muted-foreground">{t(x.hint)}</p>
            </div>
            <Switch id={`jv-${x.k}`} checked={settings[x.k]} onCheckedChange={(v) => set(x.k, v)} />
          </div>
        ))}
        <div className="grid grid-cols-2 gap-3">
          <TimeField icon={Sun} label={t('jarvis.set.brief')} value={settings.brief} onSave={(v) => set('brief', v)} />
          <TimeField icon={Moon} label={t('jarvis.set.dream')} value={settings.dream} onSave={(v) => set('dream', v)} />
        </div>
        <div className="grid gap-1">
          <span className="text-sm">{t('jarvis.set.compact')}</span>
          <Select
            value={String(settings.compact_tokens ?? 0)}
            onValueChange={(v) => set('compact_tokens', Number(v))}
            options={COMPACT_AT.map((n) => ({ value: String(n), label: n ? `${n / 1000}k` : t('jarvis.set.compactSame') }))}
            className="h-8"
            data-testid="jarvis-compact"
          />
          <p className="text-xs text-muted-foreground">{t('jarvis.set.compactHint')}</p>
        </div>
        <div className="grid gap-1">
          <span className="text-sm">{t('jarvis.set.telegram')}</span>
          <Select
            value={settings.telegram || 'important'}
            onValueChange={(v) => set('telegram', v)}
            options={(['important', 'all', 'off'] as const).map((v) => ({ value: v, label: t(`jarvis.set.telegram.${v}`) }))}
            className="h-8"
            data-testid="jarvis-telegram"
          />
          <p className="text-xs text-muted-foreground">
            {tg && !tg.chat ? (
              <Link to="/settings/telegram" className="underline underline-offset-2">
                {t('jarvis.set.telegramOff')}
              </Link>
            ) : (
              t('jarvis.set.telegramHint')
            )}
          </p>
        </div>
        <p className="text-xs text-muted-foreground">{t('jarvis.set.cost')}</p>
        <div className="flex flex-wrap gap-2 border-t pt-3">
          <Tooltip content={t('jarvis.new.hint')}>
            <Button variant="outline" size="sm" onClick={onNew} disabled={renewing} data-testid="jarvis-new">
              <MessageSquarePlus />
              {t('jarvis.new')}
            </Button>
          </Tooltip>
          <Button variant="outline" size="sm" onClick={() => brief.mutate()} disabled={brief.isPending}>
            <Sun />
            {t('jarvis.set.briefNow')}
          </Button>
          <Button variant="outline" size="sm" onClick={() => dream.mutate()} disabled={dream.isPending}>
            <Moon />
            {t('jarvis.set.dreamNow')}
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  )
}

function TimeField({ icon: Icon, label, value, onSave }: { icon: typeof Sun; label: string; value: string; onSave: (v: string) => void }) {
  const t = useT()
  const [v, setV] = React.useState(value)
  React.useEffect(() => setV(value), [value])
  return (
    <label className="grid gap-1 text-xs text-muted-foreground">
      <span className="flex items-center gap-1">
        <Icon className="size-3.5" />
        {label}
      </span>
      <div className="flex items-center gap-1">
        <Input type="time" value={v} onChange={(e) => setV(e.target.value)} onBlur={() => v !== value && onSave(v)} className="h-8" />
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
