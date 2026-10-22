// Ready-made layouts (like the snap layouts of a desktop). Three ways in:
// - hold a column's grip still (HOLD_MS): a picker opens next to it, a click on a zone puts that session there and
//   the others fill the rest in their order;
// - drag a column by its grip: a bar slides down at the top of the strip, unfolds when the drag reaches it, and
//   dropping on a zone does the same;
// - rest the pointer on the grid button (HOVER_MS): a click on a layout arranges every open session.
// The column menu opens the grip's picker for the keyboard.
import * as React from 'react'
import { LayoutGrid } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Popover, PopoverAnchor, PopoverContent } from '@/components/ui/popover'
import { fitting, layoutId, layoutName, layoutsFor, MIN_W, slotsOf, type Slot } from './layouts'
import { useSessionsUI } from './store'

const HOVER_MS = 200
const HOLD_MS = 250
const LEAVE_MS = 150

export function LayoutPicker({
  count,
  colKey,
  open: openProp,
  onOpenChange,
  holdOpens,
  children,
}: {
  count: number
  /** Opened from this column's grip: a zone click moves it there. */
  colKey?: string
  /** Controlled opening (keyboard: the column menu). */
  open?: boolean
  onOpenChange?: (open: boolean) => void
  /** Opens when the anchor is held still (grip), instead of hovered (grid button). */
  holdOpens?: boolean
  children: React.ReactElement
}) {
  const [hoverOpen, setHoverOpen] = React.useState(false)
  const [held, setHeld] = React.useState(false)
  const [holding, setHolding] = React.useState(false)
  const open = openProp || hoverOpen || held
  const viaKeyboard = !!openProp
  const sticky = viaKeyboard || held
  const timer = React.useRef<ReturnType<typeof setTimeout>>(undefined)
  const downAt = React.useRef<{ x: number; y: number } | null>(null)
  const clear = () => clearTimeout(timer.current)
  const later = (v: boolean, ms: number) => {
    clear()
    timer.current = setTimeout(() => setHoverOpen(v), ms)
  }
  React.useEffect(() => clear, [])
  const setOpen = (v: boolean) => {
    clear()
    setHoverOpen(v)
    if (!v) {
      setHeld(false)
      onOpenChange?.(false)
    }
  }
  const enabled = count >= 2
  const stopHold = () => {
    if (!downAt.current) return
    downAt.current = null
    setHolding(false)
    clear()
  }

  return (
    <Popover open={enabled && open} onOpenChange={setOpen}>
      <PopoverAnchor asChild>
        <span
          className={cn('inline-flex [&>*]:transition-[transform,color] [&>*]:duration-200', holding && '[&>*]:scale-125 [&>*]:text-primary')}
          onPointerEnter={(e) => !holdOpens && e.pointerType === 'mouse' && enabled && later(true, open ? 0 : HOVER_MS)}
          onPointerLeave={() => {
            stopHold()
            if (!sticky) later(false, LEAVE_MS)
          }}
          onPointerDown={(e) => {
            if (!holdOpens) return setOpen(false)
            if (e.button !== 0 || !enabled) return
            downAt.current = { x: e.clientX, y: e.clientY }
            setHolding(true)
            clear()
            timer.current = setTimeout(() => {
              downAt.current = null
              setHolding(false)
              setHeld(true)
            }, HOLD_MS)
          }}
          onPointerMove={(e) => {
            const d = downAt.current
            if (d && Math.hypot(e.clientX - d.x, e.clientY - d.y) > 4) stopHold()
          }}
          onPointerUp={stopHold}
          onDragStart={() => {
            stopHold()
            setOpen(false)
          }}
          data-holding={holding || undefined}
        >
          {children}
        </span>
      </PopoverAnchor>
      <PopoverContent
        align="start"
        className="w-auto p-3 origin-(--radix-popover-content-transform-origin)"
        onOpenAutoFocus={(e) => !viaKeyboard && e.preventDefault()}
        onCloseAutoFocus={(e) => !viaKeyboard && e.preventDefault()}
        onPointerEnter={clear}
        onPointerLeave={() => !sticky && later(false, LEAVE_MS)}
        data-testid="layout-picker"
      >
        <Picker count={count} colKey={colKey} onDone={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  )
}

function Picker({ count, colKey, onDone }: { count: number; colKey?: string; onDone: () => void }) {
  const t = useT()
  const cols = useSessionsUI((s) => s.cols)
  const current = layoutId(slotsOf(cols))
  const mine = colKey ? cols.findIndex((c) => c.key === colKey) : -1
  const layouts = React.useMemo(() => fitting(layoutsFor(count), stripRoom(), MIN_W), [count])
  return (
    <div className="grid gap-2">
      <div className="text-[12px] font-medium text-muted-foreground">{t('sessions.layout.title')}</div>
      <div className="grid grid-cols-2 gap-2">
        {layouts.map((slots, i) => (
          <Thumb
            key={layoutId(slots)}
            i={i}
            slots={slots}
            current={layoutId(slots) === current}
            mine={layoutId(slots) === current ? mine : -1}
            perZone={!!colKey}
            onPick={(zone) => {
              useSessionsUI.getState().applyLayout(slots, colKey ? { key: colKey, zone } : undefined)
              onDone()
            }}
          />
        ))}
      </div>
      <p className="max-w-[15rem] text-[11px] leading-snug text-muted-foreground">{colKey ? t('sessions.layout.hintCol') : t('sessions.layout.hint')}</p>
    </div>
  )
}

/** While a column is dragged by its grip: a pill slides down at the top of the strip, unfolds into the layouts when
 *  the drag reaches it; dropping on a zone puts the dragged session there. */
export function LayoutDropBar() {
  const t = useT()
  const dragging = useSessionsUI((s) => s.dragging)
  const cols = useSessionsUI((s) => s.cols)
  const [over, setOver] = React.useState(false)
  const [lit, setLit] = React.useState<{ id: string; zone: number } | null>(null)
  const leave = React.useRef<ReturnType<typeof setTimeout>>(undefined)
  const shown = !!dragging && cols.length >= 2
  React.useEffect(() => {
    if (shown) return
    setOver(false)
    setLit(null)
  }, [shown])
  // a drag that ends anywhere (Escape, dropped outside the window) hides the bar
  React.useEffect(() => {
    if (!dragging) return
    const end = () => useSessionsUI.getState().setDragging(null)
    document.addEventListener('dragend', end)
    document.addEventListener('drop', end)
    return () => {
      document.removeEventListener('dragend', end)
      document.removeEventListener('drop', end)
    }
  }, [dragging])
  const current = layoutId(slotsOf(cols))
  return (
    <div
      className={cn(
        'pointer-events-none absolute inset-x-0 top-2 z-30 flex justify-center transition-[opacity,transform] duration-150 ease-out will-change-transform',
        shown ? 'translate-y-0 opacity-100' : '-translate-y-4 opacity-0',
      )}
      data-testid="layout-drop-bar"
      data-open={over || undefined}
    >
      <div
        className={cn('rounded-xl border bg-popover px-3 py-1.5 text-popover-foreground shadow-pop', shown && 'pointer-events-auto')}
        onDragEnter={(e) => {
          if (!dragging) return
          e.preventDefault()
          clearTimeout(leave.current)
          setOver(true)
        }}
        onDragOver={(e) => {
          if (!dragging) return
          e.preventDefault()
          e.stopPropagation()
          e.dataTransfer.dropEffect = 'move'
          clearTimeout(leave.current)
        }}
        onDragLeave={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node)) return
          clearTimeout(leave.current)
          leave.current = setTimeout(() => {
            setOver(false)
            setLit(null)
          }, 180)
        }}
        onDrop={(e) => e.preventDefault()}
      >
        <div className="flex items-center justify-center gap-1.5 text-[12px] font-medium text-muted-foreground">
          <LayoutGrid className="size-3.5" />
          {over ? t('sessions.layout.release') : t('sessions.layout.dragHere')}
        </div>
        <div className={cn('grid transition-[grid-template-rows,opacity] duration-150 ease-out', over ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0')}>
          <div className="min-h-0 overflow-hidden">
            {over && (
              <div className="flex gap-2 pt-2 pb-1">
                {fitting(layoutsFor(cols.length), stripRoom(), MIN_W).map((slots, i) => {
                  const id = layoutId(slots)
                  return (
                    <Thumb
                      key={id}
                      i={i}
                      slots={slots}
                      current={id === current}
                      mine={-1}
                      perZone
                      lit={lit?.id === id ? lit.zone : null}
                      onZoneDragOver={(zone) => (lit?.id !== id || lit.zone !== zone) && setLit({ id, zone })}
                      onPick={(zone) => {
                        if (dragging) useSessionsUI.getState().applyLayout(slots, { key: dragging, zone })
                        useSessionsUI.getState().setDragging(null)
                      }}
                    />
                  )
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/** One layout drawn small: its zones, lit on hover (all of them from the grid button, one from a grip) or under a
 *  drag (`lit`). */
function Thumb({
  slots,
  i,
  current,
  mine,
  perZone,
  lit,
  onZoneDragOver,
  onPick,
}: {
  slots: Slot[]
  i: number
  current: boolean
  mine: number
  perZone: boolean
  lit?: number | null
  onZoneDragOver?: (zone: number) => void
  onPick: (zone: number) => void
}) {
  const t = useT()
  let n = 0
  const zones: { col: number; row: string; zone: number }[] = []
  slots.forEach((s, c) => {
    if (s === 'pair') {
      zones.push({ col: c + 1, row: '1', zone: n++ }, { col: c + 1, row: '2', zone: n++ })
    } else zones.push({ col: c + 1, row: '1 / span 2', zone: n++ })
  })
  return (
    <div className="group mx-unfold grid w-[7.25rem] shrink-0 gap-1" style={{ '--i': i } as React.CSSProperties}>
    <div
      className={cn(
        'grid h-14 gap-[3px] rounded-md border p-[3px] transition-[border-color,box-shadow] duration-100',
        current ? 'border-primary/70' : 'group-hover:border-foreground/30',
        lit != null && 'border-foreground/30 shadow-sm',
      )}
      style={{ gridTemplateColumns: slots.map((s) => (s === 'big' ? '2fr' : '1fr')).join(' '), gridTemplateRows: '1fr 1fr' }}
    >
      {zones.map((z) => (
        <button
          key={z.zone}
          type="button"
          aria-label={t('sessions.layout.zone', { n: z.zone + 1 })}
          onClick={() => onPick(z.zone)}
          onDragOver={
            onZoneDragOver &&
            ((e) => {
              e.preventDefault()
              onZoneDragOver(z.zone)
            })
          }
          onDrop={
            onZoneDragOver &&
            ((e) => {
              e.preventDefault()
              e.stopPropagation()
              onPick(z.zone)
            })
          }
          className={cn(
            'min-w-0 rounded-[3px] outline-none transition-colors duration-100 focus-visible:bg-primary',
            lit === z.zone ? 'bg-primary' : z.zone === mine ? 'bg-primary/45' : 'bg-muted-foreground/20',
            perZone ? 'hover:bg-primary' : 'group-hover:bg-primary/75',
          )}
          style={{ gridColumn: z.col, gridRow: z.row }}
          data-zone={z.zone}
        />
      ))}
    </div>
    <div className={cn('truncate text-center text-[10.5px] leading-tight', current ? 'text-foreground' : 'text-muted-foreground')}>{t(`sessions.layout.name.${layoutName(slots)}`)}</div>
    </div>
  )
}

/** Width of the sessions strip (what the layouts must fit in). */
function stripRoom(): number {
  return document.querySelector<HTMLElement>('[data-columns]')?.clientWidth ?? window.innerWidth
}
