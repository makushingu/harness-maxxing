import * as React from 'react'
import { useNavigate } from 'react-router'
import { Command as Cmdk } from 'cmdk'
import * as DialogPrimitive from '@radix-ui/react-dialog'
import { Brain, BookOpen, Compass, CornerDownLeft, Download, Eye, File, FileText, Folder, GraduationCap, Hash, Keyboard, ListChecks, LogOut, MessageSquarePlus, MessagesSquare, Moon, Search, Sun } from 'lucide-react'
import { api } from '@/lib/api'
import { useDocs, useLogout, useWorkspace } from '@/lib/queries'
import type { FileSearchHit, SearchHit, SearchResult } from '@/lib/types'
import { useUI, resolveTheme } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
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
  const logout = useLogout()
  const theme = useUI((s) => s.theme)
  const setTheme = useUI((s) => s.setTheme)
  const setPresentation = useUI((s) => s.setPresentation)
  const openShortcuts = useShortcutsDialog((s) => s.setOpen)
  const { data: ws } = useWorkspace()
  const tutorialPath = TUTORIAL_PATHS.find((tp) => ws?.projects.some((p) => p.topics.some((x) => x.path === tp))) || null
  const { data: docs } = useDocs()
  const install = useInstallMode()

  React.useEffect(() => {
    if (!open) setQ('')
  }, [open])

  // Async: files, sessions, registered providers.
  const [asyncResults, setAsync] = React.useState<{ q: string; cmds: Command[] }>({ q: '', cmds: [] })
  const [loading, setLoading] = React.useState(false)
  React.useEffect(() => {
    if (!open || dq.length < 2) {
      setAsync({ q: '', cmds: [] })
      return
    }
    const ctrl = new AbortController()
    setLoading(true)
    const fileGroup = t('palette.files')
    // One full-text search (sessions, memory, tasks, file contents: /api/search) + file and folder NAMES
    // (/api/files/search: also finds images, folders, binaries). Content hits come first; a name hit for a
    // file already found by its content is dropped.
    const GROUP: Record<SearchHit['kind'], string> = { session: t('palette.sessions'), memory: t('palette.memory'), task: t('palette.tasks'), file: fileGroup }
    const ICON = { session: MessagesSquare, memory: Brain, task: ListChecks, file: FileText }
    const content = api
      .get<SearchResult>('/api/search', { q: dq, limit: 24 }, { signal: ctrl.signal })
      .then((r) =>
        r.results.map<Command>((h) => ({
          id: `${h.kind}:${h.id}`,
          title: h.title,
          hint: h.kind === 'task' ? undefined : h.path,
          detail: h.snippet,
          group: GROUP[h.kind],
          icon: ICON[h.kind],
          sensitive: true,
          perform: ({ navigate }) =>
            navigate(
              h.kind === 'session'
                ? `/sessions?path=${encodeURIComponent(h.path)}&session=${h.id}`
                : h.kind === 'task'
                  ? `/tasks?task=${encodeURIComponent(h.id)}`
                  : `/files?path=${encodeURIComponent(h.path)}`,
            ),
        })),
      )
      .catch(() => [] as Command[])
    const names = api
      .get<FileSearchHit[]>('/api/files/search', { q: dq }, { signal: ctrl.signal })
      .then((hits) =>
        hits.slice(0, 8).map<Command>((h) => ({
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
      setAsync({ q: dq, cmds: all.flat() })
      setLoading(false)
    })
    return () => ctrl.abort()
  }, [dq, open, providers, t])

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
      { id: 'help:tour', title: t('tour.take'), group: t('help.title'), icon: Compass, keywords: ['tour', 'help', 'guide', 'onboarding', 'visite', 'aide'], perform: () => startTour() },
      ...(tutorialPath
        ? [{ id: 'help:tutorial', title: t('tour.tutorial'), group: t('help.title'), icon: GraduationCap, keywords: ['tutorial', 'learn', 'tutoriel'], perform: ({ navigate }) => navigate(tutorialHref(tutorialPath)) } satisfies Command]
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
        keywords: s.keywords?.split(' '),
        perform: ({ navigate }) => navigate(s.id === 'docs' ? '/docs' : `/settings/${s.id}`),
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
    for (const d of docs || [])
      list.push({ id: `doc:${d.slug}`, title: d.title, hint: d.section, group: docsG, icon: BookOpen, perform: ({ navigate }) => navigate(`/docs/${d.slug}`) })
    return list
  }, [t, theme, presentation, ws, docs, setTheme, setPresentation, openShortcuts, logout, install, tutorialPath, navItems])

  const pageCmds = Object.values(sources).flat()
  const all = [...pageCmds, ...staticCmds]
  const groups = groupBy(all)
  const asyncGroups = groupBy(asyncResults.q === dq ? asyncResults.cmds : [])

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
          <Cmdk label={t('palette.title')} className="flex min-h-0 flex-1 flex-col" loop>
            <div className="flex items-center gap-2 border-b px-4">
              <Search className="size-4 shrink-0 text-muted-foreground" />
              <Cmdk.Input
                value={q}
                onValueChange={setQ}
                placeholder={t('palette.placeholder')}
                className="h-13 min-w-0 flex-1 bg-transparent text-[15px] outline-none placeholder:text-muted-foreground max-md:h-14 max-md:text-base"
              />
              {loading && <Spinner className="text-muted-foreground" />}
              <button type="button" onClick={close} className="text-sm text-muted-foreground md:hidden">
                {t('common.cancel')}
              </button>
              <Kbd className="max-md:hidden">Esc</Kbd>
            </div>
            <Cmdk.List className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-2 md:max-h-[440px]">
              <Cmdk.Empty className="py-10 text-center text-sm text-muted-foreground">{loading ? t('palette.searching') : t('palette.empty')}</Cmdk.Empty>
              {Object.entries(groups).map(([g, cmds]) => (
                <Cmdk.Group key={g} heading={g} className={groupCls}>
                  {cmds.map((c) => (
                    <Item key={c.id} c={c} onRun={run} masked={presentation && c.sensitive} />
                  ))}
                </Cmdk.Group>
              ))}
              {Object.entries(asyncGroups).map(([g, cmds]) => (
                <Cmdk.Group key={`a:${g}`} heading={g} className={groupCls} forceMount>
                  {cmds.map((c) => (
                    <Item key={c.id} c={c} onRun={run} masked={presentation && c.sensitive} force />
                  ))}
                </Cmdk.Group>
              ))}
            </Cmdk.List>
            <div className="flex items-center gap-4 border-t px-4 py-2 text-xs text-muted-foreground max-md:hidden">
              <span className="flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd> {t('palette.move')}
              </span>
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

function groupBy(cmds: Command[]) {
  const out: Record<string, Command[]> = {}
  for (const c of cmds) (out[c.group] ||= []).push(c)
  return out
}
