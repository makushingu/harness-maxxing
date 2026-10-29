// Several entries at once in a folder (Files page listing, folder grid of the file viewer). A long press (finger,
// or a mouse button held still) starts a selection, then a tap toggles an entry and a long press on another one
// adds the range from the last one touched. Desktop: Shift+click = range from the last item clicked, Ctrl/Cmd+click
// = toggle one, Ctrl/Cmd+A = all, Escape = none. Right click (Shift+F10, the menu key) = the actions of the entry,
// or of the whole selection when the entry is part of it.
// Events are delegated to the container: an item only carries `data-row` + `data-path` (and the `mx-tile` class),
// so a toggle re-renders that item and the bar, never the whole folder, and no timer runs per item.
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'
import { Check, Copy, Download, Eye, FolderOpen, MoreHorizontal, Pencil, Trash2, X } from 'lucide-react'
import {
  Button,
  confirm,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  toast,
  Tooltip,
  useMask,
} from '@/components/ui'
import { api, errorMessage } from '@/lib/api'
import { qk } from '@/lib/queries/keys'
import type { FileEntry } from '@/lib/types'
import { cn, copyText } from '@/lib/utils'
import { useT } from '@/i18n'
import { basename, dirname } from './kinds'
import { useDownloadEntries } from './download'

const LONG_PRESS_MS = 450
const MOVE_PX = 8
const NONE: ReadonlySet<string> = new Set()

export type MenuAt = { x: number; y: number; entries: FileEntry[] }

type Gesture = { timer: number; x: number; y: number; type: string; fired: boolean }

const itemAt = (t: EventTarget | null) => (t instanceof Element ? t.closest<HTMLElement>('[data-row][data-path]') : null)
const typing = (t: EventTarget | null) => t instanceof HTMLElement && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))

/** Selection state of one folder view and the delegated handlers of its container (`bind`). `entries`: in the
 *  order shown (ranges follow it); entries that leave it (deleted, renamed, filtered out) leave the selection.
 *  `root`: the element around the items and the bar (Escape clears while the focus is inside, or nowhere). */
export function useEntrySelection({ entries, onOpen, root }: { entries: FileEntry[]; onOpen: (e: FileEntry) => void; root: React.RefObject<HTMLElement | null> }) {
  const [selected, setSelected] = React.useState<ReadonlySet<string>>(NONE)
  const [menu, setMenu] = React.useState<MenuAt | null>(null)
  const anchor = React.useRef<string | null>(null)
  const g = React.useRef<Gesture>({ timer: 0, x: 0, y: 0, type: '', fired: false })
  const byPath = React.useMemo(() => new Map(entries.map((e, i) => [e.path, i])), [entries])
  const live = React.useRef({ entries, byPath, selected, onOpen })
  live.current = { entries, byPath, selected, onOpen }

  // The folder changed or entries went away: keep only what is still shown.
  React.useEffect(() => {
    setSelected((s) => {
      if (!s.size) return s
      const kept = [...s].filter((p) => byPath.has(p))
      return kept.length === s.size ? s : new Set(kept)
    })
    if (anchor.current && !byPath.has(anchor.current)) anchor.current = null
  }, [byPath])

  const clear = React.useCallback(() => {
    setSelected(NONE)
    anchor.current = null
  }, [])
  const toggle = React.useCallback((p: string) => {
    anchor.current = p
    setSelected((s) => {
      const n = new Set(s)
      if (!n.delete(p)) n.add(p)
      return n
    })
  }, [])
  /** Adds the entries from the anchor to `p` (both included); no anchor: `p` alone. */
  const range = React.useCallback((p: string) => {
    const { entries, byPath } = live.current
    const a = anchor.current != null ? byPath.get(anchor.current) : undefined
    const b = byPath.get(p)
    if (b == null) return
    const [from, to] = a == null ? [b, b] : [Math.min(a, b), Math.max(a, b)]
    setSelected((s) => {
      const n = new Set(s)
      for (let i = from; i <= to; i++) n.add(entries[i].path)
      return n
    })
    if (a == null) anchor.current = p
  }, [])
  const selectAll = React.useCallback(() => setSelected(new Set(live.current.entries.map((e) => e.path))), [])

  const cancelPress = () => {
    window.clearTimeout(g.current.timer)
    g.current.timer = 0
  }
  React.useEffect(() => () => window.clearTimeout(g.current.timer), [])

  const longPress = (p: string) => {
    g.current.fired = true
    navigator.vibrate?.(12)
    if (!live.current.selected.size || anchor.current == null) {
      anchor.current = p
      setSelected((s) => new Set(s).add(p))
    } else range(p)
  }

  const openMenu = (el: HTMLElement, x?: number, y?: number) => {
    const { entries, byPath, selected } = live.current
    const p = el.dataset.path!
    const i = byPath.get(p)
    if (i == null) return
    const r = el.getBoundingClientRect()
    setMenu({
      x: x || r.left + Math.min(24, r.width / 2),
      y: y || r.top + Math.min(24, r.height / 2),
      entries: selected.has(p) ? entries.filter((e) => selected.has(e.path)) : [entries[i]],
    })
  }

  // Escape clears before anything else hears it (the file viewer closes on Escape), unless a menu or another
  // dialog is in front or a field has the focus (the filter clears itself first).
  const selecting = selected.size > 0
  React.useEffect(() => {
    if (!selecting || menu) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      const t = e.target as Node | null
      if (typing(t) || (t !== document.body && !root.current?.contains(t))) return
      e.preventDefault()
      e.stopPropagation()
      clear()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [selecting, menu, root, clear])

  const bind = {
    'data-selecting': selecting || undefined,
    onPointerDown: (e: React.PointerEvent) => {
      g.current.fired = false
      if (e.button !== 0) return
      const el = itemAt(e.target)
      if (!el) return
      cancelPress()
      Object.assign(g.current, { x: e.clientX, y: e.clientY, type: e.pointerType })
      const p = el.dataset.path!
      g.current.timer = window.setTimeout(() => {
        g.current.timer = 0
        longPress(p)
      }, LONG_PRESS_MS)
    },
    onPointerMove: (e: React.PointerEvent) => {
      if (g.current.timer && Math.hypot(e.clientX - g.current.x, e.clientY - g.current.y) > MOVE_PX) cancelPress()
    },
    onPointerUp: () => {
      cancelPress()
      // the click that follows a long press must not open (or toggle) the entry
      if (g.current.fired) window.setTimeout(() => (g.current.fired = false), 400)
    },
    onPointerCancel: cancelPress,
    onDragStart: cancelPress,
    onClick: (e: React.MouseEvent) => {
      const el = itemAt(e.target)
      if (!el) return
      const p = el.dataset.path!
      if (g.current.fired) {
        g.current.fired = false
        e.preventDefault()
        return
      }
      const { entries, byPath, selected, onOpen } = live.current
      const i = byPath.get(p)
      if (i == null) return
      if (e.metaKey || e.ctrlKey) toggle(p)
      else if (e.shiftKey) range(p)
      else if (selected.size) toggle(p)
      else {
        anchor.current = p
        onOpen(entries[i])
      }
    },
    onContextMenu: (e: React.MouseEvent) => {
      const el = itemAt(e.target)
      if (!el) return
      e.preventDefault()
      // Android: the long press of a finger is a contextmenu - it selects, like everywhere else.
      if (g.current.type === 'touch' && (g.current.timer || g.current.fired)) {
        if (!g.current.fired) {
          cancelPress()
          longPress(el.dataset.path!)
        }
        return
      }
      cancelPress()
      openMenu(el, e.clientX, e.clientY)
    },
    onKeyDown: (e: React.KeyboardEvent) => {
      if (typing(e.target)) return
      if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === 'a') {
        e.preventDefault()
        selectAll()
      } else if (e.key === 'ContextMenu' || (e.shiftKey && e.key === 'F10')) {
        const el = itemAt(document.activeElement)
        if (!el) return
        e.preventDefault()
        openMenu(el)
      }
    },
  }

  return { selected, selecting, clear, selectAll, menu, closeMenu: () => setMenu(null), openMenu, bind }
}

/* ------------------------------------------------------------------ actions */
/** Copy the paths of entries, one per line. */
export function useCopyPaths() {
  const t = useT()
  return (paths: string[]) => void copyText(paths.join('\n')).then((ok) => ok && toast.success(t('files.sel.pathsCopied', { count: paths.length })))
}

/** Move entries to the trash after one confirmation (their count and first names); returns the paths deleted.
 *  A stable function: the Files page's entry actions depend on it, and a new one each render re-rendered every row. */
export function useRemoveEntries() {
  const t = useT()
  const qc = useQueryClient()
  const mask = useMask()
  return React.useCallback(async (paths: string[]): Promise<string[]> => {
    if (!paths.length) return []
    const names = paths.slice(0, 5).map((p) => mask(basename(p), 8))
    const ok = await confirm(
      paths.length === 1
        ? { title: t('files.deleteTitle', { name: names[0] }), description: t('files.deleteDesc'), destructive: true, confirmText: t('files.moveToTrash') }
        : {
            title: t('files.sel.deleteTitle', { count: paths.length }),
            description: (
              <>
                <span className="block break-all" data-testid="delete-names">
                  {names.join(', ')}
                  {paths.length > names.length && ` ${t('files.sel.andMore', { count: paths.length - names.length })}`}
                </span>
                <span className="mt-2 block">{t('files.deleteDesc')}</span>
              </>
            ),
            destructive: true,
            confirmText: t('files.moveToTrash'),
          },
    )
    if (!ok) return []
    const done: string[] = []
    let failed: unknown = null
    for (const p of paths) {
      try {
        await api.post('/api/files/delete', { path: p })
        done.push(p)
        qc.removeQueries({ queryKey: qk.files.read(p) })
        qc.removeQueries({ queryKey: ['files', 'kind', p] })
      } catch (e) {
        failed ??= e
      }
    }
    await Promise.all([...new Set(paths.map(dirname))].map((d) => qc.invalidateQueries({ queryKey: qk.files.list(d) })))
    if (failed) toast.error(t('files.deleteFailed'), errorMessage(failed))
    if (done.length) toast.success(done.length === 1 ? t('files.movedToTrash', { name: mask(basename(done[0]), 8) }) : t('files.sel.movedToTrash', { count: done.length }))
    return done
  }, [t, qc, mask])
}

export type SelectionActions = {
  open: (e: FileEntry) => void
  /** The file viewer: leave it for the Files page on that entry. */
  openInFiles?: (e: FileEntry) => void
  rename?: (e: FileEntry) => void
  /** Deleted entries (after its confirmation). */
  remove: (entries: FileEntry[]) => void
}

/** The actions of one entry or of several (a right click, the bar's "More"). */
function MenuItems({ entries, actions }: { entries: FileEntry[]; actions: SelectionActions }) {
  const t = useT()
  const download = useDownloadEntries()
  const copyPaths = useCopyPaths()
  const one = entries.length === 1 ? entries[0] : null
  return (
    <>
      {!one && <DropdownMenuLabel className="tabular-nums">{t('files.sel.count', { count: entries.length })}</DropdownMenuLabel>}
      {one && (
        <DropdownMenuItem onSelect={() => actions.open(one)} data-testid="sel-open">
          <Eye />
          {t('files.open')}
        </DropdownMenuItem>
      )}
      {one && actions.openInFiles && (
        <DropdownMenuItem onSelect={() => actions.openInFiles!(one)}>
          <FolderOpen />
          {t('files.openInFiles')}
        </DropdownMenuItem>
      )}
      <DropdownMenuItem onSelect={() => download(entries)} data-testid="sel-download">
        <Download />
        {one ? (one.type === 'dir' ? t('files.downloadZip') : t('files.download')) : t('files.sel.downloadZip')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => copyPaths(entries.map((e) => e.path))} data-testid="sel-copy">
        <Copy />
        {one ? t('files.copyPath') : t('files.sel.copyPaths')}
      </DropdownMenuItem>
      {one && actions.rename && (
        <DropdownMenuItem onSelect={() => actions.rename!(one)}>
          <Pencil />
          {t('files.renameMove')}
        </DropdownMenuItem>
      )}
      <DropdownMenuSeparator />
      <DropdownMenuItem
        destructive
        data-testid="sel-delete"
        onSelect={() => actions.remove(entries)}
      >
        <Trash2 />
        {t('common.delete')}
      </DropdownMenuItem>
    </>
  )
}

/** The menu of a right click, at the pointer (or on the focused entry). */
export function EntriesMenu({ at, actions, onClose }: { at: MenuAt | null; actions: SelectionActions; onClose: () => void }) {
  if (!at) return null
  return createPortal(
    <DropdownMenu open onOpenChange={(o) => !o && onClose()}>
      <DropdownMenuTrigger asChild>
        <span aria-hidden tabIndex={-1} className="pointer-events-none fixed size-0" style={{ left: at.x, top: at.y }} />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" sideOffset={2} className="min-w-52" data-testid="entries-menu">
        <MenuItems entries={at.entries} actions={actions} />
      </DropdownMenuContent>
    </DropdownMenu>,
    document.body,
  )
}

/** Shown while entries are selected: their count, Download, Delete, More, Cancel. */
export function SelectionBar({ entries, actions, onSelectAll, onClear, total, className }: { entries: FileEntry[]; actions: SelectionActions; onSelectAll: () => void; onClear: () => void; total: number; className?: string }) {
  const t = useT()
  const download = useDownloadEntries()
  if (!entries.length) return null
  return (
    <div role="toolbar" aria-label={t('files.sel.bar')} className={cn('flex shrink-0 items-center gap-1 border-b bg-accent/40 px-2 py-1.5 animate-in', className)} data-testid="selection-bar">
      <Tooltip content={t('files.sel.clear')}>
        <Button variant="ghost" size="icon-sm" onClick={onClear} aria-label={t('files.sel.clear')} data-testid="sel-clear">
          <X />
        </Button>
      </Tooltip>
      <span className="min-w-0 flex-1 truncate text-sm font-medium tabular-nums" aria-live="polite" data-testid="sel-count">
        {t('files.sel.count', { count: entries.length })}
      </span>
      {entries.length < total && (
        <Button variant="ghost" size="sm" className="h-8 max-sm:hidden" onClick={onSelectAll}>
          {t('files.sel.all')}
        </Button>
      )}
      <Tooltip content={entries.length > 1 ? t('files.sel.downloadZip') : t('files.download')}>
        <Button variant="ghost" size="icon-sm" onClick={() => download(entries)} aria-label={entries.length > 1 ? t('files.sel.downloadZip') : t('files.download')} data-testid="bar-download">
          <Download />
        </Button>
      </Tooltip>
      <Tooltip content={t('common.delete')}>
        <Button variant="ghost" size="icon-sm" onClick={() => actions.remove(entries)} aria-label={t('common.delete')} data-testid="bar-delete">
          <Trash2 />
        </Button>
      </Tooltip>
      <DropdownMenu>
        <Tooltip content={t('common.more')}>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.more')} data-testid="bar-more">
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
        </Tooltip>
        <DropdownMenuContent align="end" className="min-w-52">
          <MenuItems entries={entries} actions={actions} />
          {entries.length < total && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onSelectAll}>
                <Check />
                {t('files.sel.all')}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}

/** The round check of an entry: empty while selecting, filled when it is selected (needs `group/sel` with
 *  `data-selecting` on the container: entering selection mode re-renders no item). */
export function SelectCheck({ checked, className }: { checked: boolean; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'pointer-events-none items-center justify-center rounded-full border-2 transition-colors',
        checked ? 'flex border-primary bg-primary text-primary-foreground' : 'hidden border-foreground/40 bg-background/80 group-data-[selecting]/sel:flex',
        className,
      )}
    >
      {checked && <Check className="size-3" strokeWidth={3} />}
    </span>
  )
}
