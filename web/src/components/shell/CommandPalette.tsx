import * as React from 'react'
import { useNavigate } from 'react-router'
import { Command as Cmdk, defaultFilter } from 'cmdk'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Bot, Brain, BookOpen, Compass, CornerDownLeft, Download, Eye, File, FileText, Folder, GraduationCap, Hash, Keyboard, ListChecks, LogOut, MessageSquarePlus, MessagesSquare, Moon, Search, Sun, UsersRound } from 'lucide-react'
import { api } from '@/lib/api'
import { AGENT_PATH_RE, GROUP_PATH_RE, agentRoute, agentRunRoute, groupRoute, useAgentGroups, useAgents, useDocs, useLogout, useSettings, useWorkspace } from '@/lib/queries'
import type { FileSearchHit, SearchHit, SearchResult } from '@/lib/types'
import { useUI, resolveTheme } from '@/stores/ui'
import { cn, fold } from '@/lib/utils'
import { tDyn, useT, type TKey } from '@/i18n'
import { useCommandStore, type Command } from '@/commands/registry'
import { Kbd, Spinner, usePresentation } from '@/components/ui'
import { useNav } from './nav'
import { useShortcutsDialog } from './shortcuts-store'
import { SETTINGS_SECTIONS } from '@/pages/settings/sections'
import { startTour, TUTORIAL_PATHS, tutorialHref } from '@/tour/store'
import { installApp, useInstallMode } from '@/pwa'

function useDebounced<T>(v: T, ms: number) {
  const [d, setD] = React.useState(v)
  React.useEffect(() => {
    const id = setTimeout(() => setD(v), ms)
    return () => clearTimeout(id)
  }, [v, ms])
  return d
}

export function CommandPalette() {
  const t = useT()
  const navigate = useNavigate()
  const open = useCommandStore((s) => s.open)
  const setOpen = useCommandStore((s) => s.setOpen)
  const sources = useCommandStore((s) => s.sources)
  const providers = useCommandStore((s) => s.providers)
  const presentation = usePresentation()
  const [q, setQ] = React.useState('')
  const dq = useDebounced(q.trim(), 200)
  // the chip picked above the results (a type: sessions, agents, tasks...); 'all' while nothing is typed
  const [picked, setChip] = React.useState<Chip>('all')
  const chip: Chip = q.trim() ? picked : 'all'
  const logout = useLogout()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const setPresentation = useUI((s) => s.setPresentation)
  const openShortcuts = useShortcutsDialog((s) => s.setOpen)
  const { data: ws } = useWorkspace()
  const tutorialPath = TUTORIAL_PATHS.find((tp) => ws?.projects.some((p) => p.topics.some((x) => x.path === tp))) || null
  const { data: docs } = useDocs()
  const install = useInstallMode()
  // Agents on: every agent and every group can be opened from here (lists loaded once the palette opens)
  const { data: st } = useSettings()
  const agentsOn = !!st?.agents_page
  const { data: agentList } = useAgents(open && agentsOn)
  const { data: groupList } = useAgentGroups(open && agentsOn)

  React.useEffect(() => {
    if (!open) {
      setQ('')
      setChip('all')
    }
  }, [open])

  // Async: files, sessions, registered providers.
  const [asyncResults, setAsync] = React.useState<{ q: string; chip?: Chip; cmds: Command[] }>({ q: '', cmds: [] })
  const [loading, setLoading] = React.useState(false)
  React.useEffect(() => {
    if (!open || dq.length < 2) {
      setAsync({ q: '', cmds: [] })
      setCounts({ q: '', n: {} })
      return
    }
    const ctrl = new AbortController()
    setLoading(true)
    // a chip of a type the full-text index holds: that type only, and more of it
    const kinds = CHIPS.find((c) => c.key === chip)?.kinds
    const query = kinds ? { q: dq, limit: 60, kinds: kinds.join(',') } : { q: dq, limit: 36 }
    const fileGroup = t('palette.files')
    // One full-text search (sessions, memory, tasks, file contents: /api/search) + file and folder NAMES
    // (/api/files/search: also finds images, folders, binaries). Content hits come first; a name hit for a
    // file already found by its content is dropped.
    const GROUP: Record<SearchHit['kind'], string> = { session: t('palette.sessions'), memory: t('palette.memory'), task: t('palette.tasks'), file: fileGroup, group: t('palette.groups') }
    const ICON = { session: MessagesSquare, memory: Brain, task: ListChecks, file: FileText, group: UsersRound }
    const groupHref = (path: string) => {
      const m = GROUP_PATH_RE.exec(path)
      return m ? groupRoute({ project: m[1], name: m[2] }) : '/agents'
    }
    const content = api
      .get<SearchResult>('/api/search', query, { signal: ctrl.signal })
      .then((r) =>
        r.results.map<Command>((h) => ({
          // a run of an agent goes with the agents (its chip), the other sessions with the sessions
          id: `${h.kind === 'session' && AGENT_PATH_RE.test(h.path) ? 'run' : h.kind}:${h.id}`,
          title: h.title,
          hint: h.kind === 'task' || h.kind === 'group' ? undefined : h.path,
          detail: h.snippet,
          group: h.kind === 'session' && AGENT_PATH_RE.test(h.path) ? t('palette.agentRuns') : GROUP[h.kind],
          icon: ICON[h.kind],
          sensitive: true,
          perform: ({ navigate }) =>
            navigate(
              h.kind === 'session'
                ? AGENT_PATH_RE.test(h.path)
                  ? agentRunRoute(h.path, h.id) // a run of an agent: on the Agents page
                  : `/sessions?path=${encodeURIComponent(h.path)}&session=${h.id}`
                : h.kind === 'task'
                  ? `/tasks?task=${encodeURIComponent(h.id)}`
                  : h.kind === 'group'
                    ? groupHref(h.path)
                    : `/files?path=${encodeURIComponent(h.path)}`,
            ),
        })),
      )
      .catch(() => [] as Command[])
    const names = api
      .get<FileSearchHit[]>('/api/files/search', { q: dq }, { signal: ctrl.signal })
      .then((hits) =>
        hits.slice(0, chip === 'files' ? 40 : 8).map<Command>((h) => ({
          id: `name:${h.path}`,
          title: h.name,
          hint: h.path,
          group: fileGroup,
          icon: h.type === 'dir' ? Folder : File,
          sensitive: true,
          perform: ({ navigate }) => navigate(`/files?path=${encodeURIComponent(h.path)}`),
        })),
      )
      .catch(() => [] as Command[])
    const tasks: Promise<Command[]>[] = [
      Promise.all([content, names]).then(([c, n]) => {
        const paths = new Set(c.filter((x) => x.hint).map((x) => x.hint))
        return [...c, ...n.filter((x) => !paths.has(x.hint))]
      }),
      ...Object.values(providers)
        .filter((p) => dq.length >= (p.minQuery ?? 2))
        .map((p) => Promise.resolve(p.search(dq, ctrl.signal)).catch(() => [] as Command[])),
    ]
    Promise.all(tasks).then((all) => {
      if (ctrl.signal.aborted) return
      setAsync({ q: dq, chip, cmds: all.flat() })
      setLoading(false)
    })
    return () => ctrl.abort()
  }, [dq, open, providers, t, chip])

  const close = () => setOpen(false)
  const run = (c: Command) => {
    close()
    // Let the dialog close before navigating (focus restoration, no flash).
    requestAnimationFrame(() => c.perform({ navigate, close }))
  }

  const navItems = useNav()
  const staticCmds = React.useMemo<Command[]>(() => {
    const nav = t('palette.navigation')
    const actions = t('palette.actions')
    const settings = t('nav.settings')
    const topics = t('palette.topics')
    const docsG = t('nav.docs')
    const list: Command[] = [
      ...navItems.map<Command>((n) => ({
        id: `nav:${n.to}`,
        title: t(n.label),
        group: nav,
        icon: n.icon,
        shortcut: ['G', n.key.toUpperCase()],
        perform: ({ navigate }) => navigate(n.to),
      })),
      { id: 'nav:docs', title: t('nav.docs'), group: nav, icon: BookOpen, perform: ({ navigate }) => navigate('/docs') },
      {
        id: 'act:theme',
        title: resolveTheme(theme) === 'dark' ? t('palette.lightTheme') : t('palette.darkTheme'),
        group: actions,
        icon: resolveTheme(theme) === 'dark' ? Sun : Moon,
        keywords: ['theme', 'dark', 'light'],
        perform: () => setTheme(resolveTheme(theme) === 'dark' ? 'light' : 'dark'),
      },
      {
        id: 'act:presentation',
        title: presentation ? t('presentation.off') : t('presentation.on'),
        group: actions,
        icon: Eye,
        shortcut: ['⇧', 'P'],
        keywords: ['presentation', 'stream', 'mask', 'privacy'],
        perform: () => setPresentation(!presentation),
      },
      { id: 'act:shortcuts', title: t('shortcuts.title'), group: actions, icon: Keyboard, shortcut: ['?'], perform: () => openShortcuts(true) },
      { id: 'help:tour', title: t('help.tour'), group: t('help.title'), icon: Compass, keywords: ['tour', 'help', 'guide', 'onboarding', 'visite', 'aide'], perform: () => startTour() },
      ...(tutorialPath
        ? [{ id: 'help:tutorial', title: t('help.tutorial'), group: t('help.title'), icon: GraduationCap, keywords: ['tutorial', 'learn', 'tutoriel'], perform: ({ navigate }) => navigate(tutorialHref(tutorialPath)) } satisfies Command]
        : []),
      ...(install
        ? [{ id: 'act:install', title: t('pwa.install'), group: actions, icon: Download, keywords: ['pwa', 'install', 'home screen', 'app'], perform: () => void installApp() } satisfies Command]
        : []),
      { id: 'act:logout', title: t('auth.signOut'), group: actions, icon: LogOut, perform: () => logout.mutate() },
      ...SETTINGS_SECTIONS.map<Command>((s) => ({
        id: `settings:${s.id}`,
        title: `${t('nav.settings')} › ${t(s.label)}`,
        group: settings,
        icon: s.icon,
        // English words + the interface language's (skw.*, its own small chunk, loaded once the palette opens)
        keywords: [...(s.keywords?.split(' ') ?? []), ...(open ? tDyn(t, `skw.${s.id}`, '').split(' ') : [])],
        perform: ({ navigate }) => navigate(`/settings/${s.id}`),
      })),
    ]
    for (const p of ws?.projects || [])
      for (const tp of p.topics) {
        list.push({
          id: `topic:${tp.path}`,
          title: `${p.name} / ${tp.name}`,
          group: topics,
          icon: Hash,
          sensitive: true,
          keywords: [p.name, tp.name, tp.description],
          perform: ({ navigate }) => navigate(`/sessions?path=${encodeURIComponent(tp.path)}`),
        })
        list.push({
          id: `topic-new:${tp.path}`,
          title: `${t('palette.newSessionIn')} ${p.name} / ${tp.name}`,
          group: topics,
          icon: MessageSquarePlus,
          sensitive: true,
          keywords: ['new', 'session', p.name, tp.name],
          perform: ({ navigate }) => navigate(`/sessions?path=${encodeURIComponent(tp.path)}&new=1`),
        })
      }
    for (const a of agentsOn ? agentList?.agents || [] : [])
      list.push({
        id: `agent:${a.path}`,
        title: a.display_name,
        hint: `${a.project} / ${a.topic}`,
        group: t('palette.agents'),
        icon: Bot,
        sensitive: true,
        keywords: [a.name, a.project, a.topic, a.description].filter(Boolean),
        perform: ({ navigate }) => navigate(agentRoute(a)),
      })
    for (const g of agentsOn ? groupList || [] : [])
      list.push({
        id: `group:${g.path}`,
        title: `${g.emoji ? `${g.emoji} ` : ''}${g.display_name}`,
        hint: g.project,
        group: t('palette.groups'),
        icon: UsersRound,
        sensitive: true,
        keywords: [g.name, g.project, ...g.members.map((m) => m.display_name)].filter(Boolean),
        perform: ({ navigate }) => navigate(groupRoute(g)),
      })
    for (const d of docs || [])
      list.push({ id: `doc:${d.slug}`, title: d.title, hint: d.section, group: docsG, icon: BookOpen, perform: ({ navigate }) => navigate(`/docs/${d.slug}`) })
    return list
  }, [t, theme, presentation, ws, docs, setTheme, setPresentation, openShortcuts, logout, install, tutorialPath, navItems, agentsOn, agentList, groupList, open])

  const pageCmds = Object.values(sources).flat()
  const all = [...pageCmds, ...staticCmds]
  const found = asyncResults.q === dq ? asyncResults.cmds : []
  // Results per chip: the commands the typed text matches (cmdk's own test) + what the search found. A chip's count
  // stays the one of the search over every type while that chip shows its own longer list.
  const matched = q.trim() ? all.filter((c) => paletteFilter(c.id + ' ' + c.title, q, c.keywords?.filter(Boolean) as string[] | undefined) > 0) : []
  const [counts, setCounts] = React.useState<{ q: string; n: Partial<Record<Chip, number>> }>({ q: '', n: {} })
  React.useEffect(() => {
    if (asyncResults.q === dq && (asyncResults.chip ?? 'all') === 'all') setCounts({ q: dq, n: countChips(asyncResults.cmds) })
  }, [asyncResults, dq])
  const staticN = countChips(matched)
  const asyncN = counts.q === dq ? counts.n : chip === 'all' ? {} : countChips(found)
  // the chip shown: its own longer list once it came
  const ownN = asyncResults.q === dq && asyncResults.chip === chip && chip !== 'all' ? countChips(found)[chip] : undefined
  const chipN = (k: Chip) => (staticN[k] ?? 0) + ((k === chip ? ownN : undefined) ?? asyncN[k] ?? 0)
  const chips = q.trim() ? CHIPS.filter((c) => c.key === 'all' || c.key === chip || chipN(c.key) > 0) : []
  const keep = (c: Command) => chip === 'all' || chipOf(c) === chip
  // cmdk sorts the items of a group by score but not the groups themselves (its group sort looks them up by a value
  // they do not carry): the group holding the best match goes first, the others keep their order
  const groups = byBestMatch(groupBy(all.filter(keep)), q)
  const asyncGroups = groupBy(found.filter(keep))
  // Every type at once: a few lines of each, then "See the N…" opens its chip
  const SHOWN = 6
  const onInputKey = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab' || chips.length < 2) return
    e.preventDefault()
    const i = chips.findIndex((c) => c.key === chip)
    setChip(chips[(i + (e.shiftKey ? -1 : 1) + chips.length) % chips.length].key)
  }

  return (
    <DialogPrimitive.Root open={open} onOpenChange={setOpen}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-overlay data-[state=open]:animate-overlay-in" />
        <DialogPrimitive.Content
          aria-describedby={undefined}
          className={cn(
            'fixed z-50 flex flex-col overflow-hidden border bg-popover text-popover-foreground shadow-pop outline-none',
            'inset-x-0 top-0 h-[100dvh] pt-[var(--safe-top)] data-[state=open]:animate-overlay-in',
            'md:inset-x-auto md:top-[12vh] md:left-1/2 md:h-auto md:max-h-[min(560px,76vh)] md:w-[640px] md:-translate-x-1/2 md:rounded-xl md:pt-0 md:data-[state=open]:animate-in',
          )}
        >
          <DialogPrimitive.Title className="sr-only">{t('palette.title')}</DialogPrimitive.Title>
          <Cmdk label={t('palette.title')} className="flex min-h-0 flex-1 flex-col" loop filter={paletteFilter}>
            <div className="flex items-center gap-2 border-b px-4">
              <Search className="size-4 shrink-0 text-muted-foreground" />
              <Cmdk.Input
                value={q}
                onValueChange={setQ}
                onKeyDown={onInputKey}
                placeholder={t('palette.placeholder')}
                className="h-13 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground max-md:h-14 max-md:text-base"
              />
              {loading && <Spinner className="text-muted-foreground" />}
              <button type="button" onClick={close} className="text-sm text-muted-foreground md:hidden pointer-coarse:min-h-11 pointer-coarse:px-2">
                {t('common.cancel')}
              </button>
              <Kbd className="max-md:hidden">Esc</Kbd>
            </div>
            {chips.length > 1 && (
              <div role="tablist" aria-label={t('palette.filter')} className="flex shrink-0 gap-1.5 overflow-x-auto border-b px-3 py-2 [scrollbar-width:none]" data-testid="palette-chips">
                {chips.map((c) => {
                  const on = c.key === chip
                  const n = c.key === 'all' ? 0 : chipN(c.key)
                  return (
                    <button
                      key={c.key}
                      type="button"
                      role="tab"
                      aria-selected={on}
                      tabIndex={-1}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => setChip(on && c.key !== 'all' ? 'all' : c.key)}
                      data-chip={c.key}
                      className={cn(
                        'flex h-7 shrink-0 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition-colors pointer-coarse:h-9 pointer-coarse:px-3',
                        on ? 'border-primary bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-accent hover:text-accent-foreground',
                      )}
                    >
                      {t(c.label)}
                      {n > 0 && <span className={cn('tabular-nums', on ? 'opacity-80' : 'opacity-70')}>{n}</span>}
                    </button>
                  )
                })}
              </div>
            )}
            <Cmdk.List className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2 md:max-h-[440px]">
              <Cmdk.Empty className="py-10 text-center text-sm text-muted-foreground">{loading ? t('palette.searching') : t('palette.empty')}</Cmdk.Empty>
              {groups.map(([g, cmds]) => (
                <Cmdk.Group key={g} heading={g} className={groupCls}>
                  {cmds.map((c) => (
                    // cmdk keeps an item's keywords from its first render: a new key when they change (skw.* arrived)
                    <Item key={`${c.id}:${c.keywords?.length ?? 0}`} c={c} onRun={run} masked={presentation && c.sensitive} />
                  ))}
                </Cmdk.Group>
              ))}
              {Object.entries(asyncGroups).map(([g, cmds]) => {
                const more = chip === 'all' && cmds.length > SHOWN + 1 ? chipOf(cmds[0]) : null
                return (
                  <Cmdk.Group key={`a:${g}`} heading={g} className={groupCls} forceMount>
                    {(more ? cmds.slice(0, SHOWN) : cmds).map((c) => (
                      <Item key={c.id} c={c} onRun={run} masked={presentation && c.sensitive} force />
                    ))}
                    {more && (
                      <Cmdk.Item value={`more:${g}`} forceMount onSelect={() => setChip(more)} className="flex h-9 cursor-default items-center gap-3 rounded-md px-2 text-xs text-muted-foreground outline-none select-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground max-md:h-11">
                        <span className="size-4 shrink-0" />
                        {t('palette.seeAll', { n: chipN(more), what: t(CHIPS.find((c) => c.key === more)!.label).toLowerCase() })}
                      </Cmdk.Item>
                    )}
                  </Cmdk.Group>
                )
              })}
            </Cmdk.List>
            <div className="flex items-center gap-4 border-t px-4 py-2 text-xs text-muted-foreground max-md:hidden">
              <span className="flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> {t('palette.move')}
              </span>
              {chips.length > 1 && (
                <span className="flex items-center gap-1.5">
                  <Kbd>Tab</Kbd> {t('palette.nextChip')}
                </span>
              )}
              <span className="flex items-center gap-1.5">
                <Kbd>
                  <CornerDownLeft className="size-3" />
                </Kbd>{' '}
                {t('palette.select')}
              </span>
            </div>
          </Cmdk>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  )
}

/** cmdk's fuzzy score on accent-folded text ("securite" finds "Sécurité"), and a whole-word match (the search found
 *  at the start of a word of the title or keywords: "mot de passe", "crons") above any fuzzy one, so the section the
 *  words name comes before actions that only contain the letters in order. */
/** The chips above the results: a type each (`kinds`: the types of the full-text index it narrows the search to).
 *  Commands of no chip (pages, actions, the providers of a page) only show under "All". */
type Chip = 'all' | 'sessions' | 'agents' | 'tasks' | 'files' | 'memory' | 'settings' | 'docs' | 'commands'
const CHIPS: { key: Chip; label: TKey; kinds?: SearchHit['kind'][] }[] = [
  { key: 'all', label: 'palette.all' },
  { key: 'sessions', label: 'palette.sessions', kinds: ['session'] },
  { key: 'agents', label: 'palette.agents', kinds: ['session', 'group'] },
  { key: 'tasks', label: 'palette.tasks', kinds: ['task'] },
  { key: 'files', label: 'palette.files', kinds: ['file'] },
  { key: 'memory', label: 'palette.memory', kinds: ['memory'] },
  { key: 'settings', label: 'nav.settings' },
  { key: 'docs', label: 'nav.docs' },
  { key: 'commands', label: 'palette.commands' },
]
const CHIP_OF: Record<string, Chip> = {
  session: 'sessions', topic: 'sessions', 'topic-new': 'sessions',
  run: 'agents', agent: 'agents', group: 'agents',
  task: 'tasks', file: 'files', name: 'files', memory: 'memory',
  settings: 'settings', doc: 'docs', nav: 'commands', act: 'commands', help: 'commands',
}
/** The chip of a command, from its id's prefix (`session:…`, `agent:…`); null: "All" only. */
function chipOf(c: Command): Chip | null {
  return CHIP_OF[c.id.slice(0, c.id.indexOf(':'))] ?? null
}
function countChips(cmds: Command[]) {
  const n: Partial<Record<Chip, number>> = {}
  for (const c of cmds) {
    const k = chipOf(c)
    if (k) n[k] = (n[k] ?? 0) + 1
  }
  return n
}

function paletteFilter(value: string, search: string, keywords?: string[]): number {
  const s = fold(search).trim()
  if (!s) return 1
  const hay = fold([value, ...(keywords ?? [])].join(' '))
  let i = hay.indexOf(s)
  while (i > 0 && /[\p{L}\p{N}]/u.test(hay[i - 1])) i = hay.indexOf(s, i + 1)
  if (i >= 0) return 2
  return defaultFilter(fold(value), s, keywords?.map(fold))
}

const groupCls =
  '[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:text-muted-foreground'

function Item({ c, onRun, masked, force }: { c: Command; onRun: (c: Command) => void; masked?: boolean; force?: boolean }) {
  const Icon = c.icon
  return (
    <Cmdk.Item
      value={c.id + ' ' + c.title}
      keywords={c.keywords?.filter(Boolean) as string[] | undefined}
      onSelect={() => onRun(c)}
      forceMount={force}
      className={cn(
        'flex cursor-default items-center gap-3 rounded-md px-2 text-sm outline-none select-none data-[selected=true]:bg-accent data-[selected=true]:text-accent-foreground',
        c.detail ? 'min-h-12 py-1.5' : 'h-10 max-md:h-12',
      )}
    >
      {Icon && <Icon className="size-4 shrink-0 text-muted-foreground" />}
      {c.detail ? (
        <span className="grid min-w-0 flex-1">
          <span className="truncate">{masked ? '••••••' : c.title}</span>
          <span className="truncate text-xs text-muted-foreground">{masked ? '••••••••••' : <Highlighted text={c.detail} />}</span>
        </span>
      ) : (
        <span className="min-w-0 flex-1 truncate">{masked ? '••••••' : c.title}</span>
      )}
      {c.hint && <span className="max-w-[45%] truncate text-xs text-muted-foreground">{masked ? '••••' : c.hint}</span>}
      {c.shortcut && (
        <span className="flex gap-1 max-md:hidden">
          {c.shortcut.map((k) => (
            <Kbd key={k}>{k}</Kbd>
          ))}
        </span>
      )}
    </Cmdk.Item>
  )
}

/** Search excerpt: the words between \u0002 and \u0003 are the matches. */
function Highlighted({ text }: { text: string }) {
  const parts = text.split(/\u0002|\u0003/)
  return (
    <>
      {parts.map((p, i) =>
        i % 2 ? (
          <mark key={i} className="rounded-sm bg-primary/20 px-0.5 text-foreground">
            {p}
          </mark>
        ) : (
          p
        ),
      )}
    </>
  )
}

function byBestMatch(groups: Record<string, Command[]>, q: string): [string, Command[]][] {
  const entries = Object.entries(groups)
  if (!q.trim()) return entries
  const best = new Map(entries.map(([g, cmds]) => [g, Math.max(0, ...cmds.map((c) => paletteFilter(c.id + ' ' + c.title, q, c.keywords?.filter(Boolean) as string[] | undefined)))]))
  return entries.sort((a, b) => best.get(b[0])! - best.get(a[0])!)
}

function groupBy(cmds: Command[]) {
  const out: Record<string, Command[]> = {}
  for (const c of cmds) (out[c.group] ||= []).push(c)
  return out
}
