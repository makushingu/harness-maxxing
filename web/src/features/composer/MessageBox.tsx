// The message box shared by every place where the user writes: a session, an agent, an agent group, a Team chat.
// Only the look and the parts every box has: the cards tucked on top (waiting messages, a notice, quotes, "replying
// to"...), a floating menu ("/", "@"), the attached files, the text that grows, and the bottom bar - attach, the
// page's tools (model, compaction gauge, poll...), its actions (Stop...), the microphone, Send. Each page keeps its
// own logic (sending, draft, menus) and fills the slots.
import * as React from 'react'
import { ArrowUp, Paperclip, Square, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Spinner, Textarea, Tooltip } from '@/components/ui'
import { AttachmentChip, type Att } from './AttachmentChip'

const RISE = 'grid transition-[grid-template-rows] duration-300 ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none'

/** A card tucked under the top of the box (same surface, -mb-3 under its rounded top). It rises when `open` becomes
 *  true and sinks back when it becomes false; the last content stays rendered while it leaves (220 ms), the height
 *  animates with grid rows (no jump of the thread above). */
export function TuckedCard({ open, children, className, ...rest }: { open: boolean; children?: React.ReactNode; className?: string } & Omit<React.HTMLAttributes<HTMLDivElement>, 'children'>) {
  const last = React.useRef<React.ReactNode>(null)
  if (open) last.current = children
  const [state, setState] = React.useState<'hidden' | 'shown' | 'leaving'>(open ? 'shown' : 'hidden')
  React.useEffect(() => {
    if (open) {
      setState('shown')
      return
    }
    setState((s) => (s === 'shown' ? 'leaving' : s))
    const id = setTimeout(() => setState((s) => (s === 'leaving' ? 'hidden' : s)), 220)
    return () => clearTimeout(id)
  }, [open])
  const node = open ? children : state === 'hidden' ? null : last.current
  const leaving = !open && state === 'leaving'
  return (
    <div className={cn(RISE, open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
      <div className="min-h-0 overflow-hidden" inert={!open ? true : undefined}>
        {node != null && node !== false && (
          <div {...rest} className={cn('relative z-0 -mb-3 rounded-t-xl border border-b-0 bg-card shadow-xs', leaving ? 'mx-queue-out' : 'mx-queue-in', className)}>
            {node}
          </div>
        )}
      </div>
    </div>
  )
}

/** The one-line head of a tucked card: an icon in the theme color, a label, an optional close button. */
export function TuckedHead({ icon, children, onClose, closeLabel, className }: { icon: React.ReactNode; children: React.ReactNode; onClose?: () => void; closeLabel?: string; className?: string }) {
  return (
    <div className={cn('flex items-center gap-1.5 px-3 pt-2 text-xs text-muted-foreground', className)}>
      <span className="flex shrink-0 text-primary [&_svg]:size-3.5">{icon}</span>
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {onClose && <CloseButton onClick={onClose} label={closeLabel || ''} />}
    </div>
  )
}

export function CloseButton({ onClick, label, disabled }: { onClick: () => void; label: string; disabled?: boolean }) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        aria-label={label}
        className="relative ml-auto -mr-1 flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground pointer-coarse:before:absolute pointer-coarse:before:-inset-2 pointer-coarse:before:content-[''] hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        <X className="size-3.5" />
      </button>
    </Tooltip>
  )
}

type SendProps = { onClick: () => void; disabled?: boolean; busy?: boolean; label: string; icon?: React.ReactNode; testId?: string }

type MessageBoxProps = {
  /** Tucked cards, top to bottom (TuckedCard). */
  above?: React.ReactNode
  /** A floating menu over the box ("/", "@"): positioned by itself (absolute, bottom-full). */
  menu?: React.ReactNode
  atts?: Att[]
  onRemoveAtt?: (lid: string) => void
  attsTestId?: string
  /** Shown above the text inside the box (e.g. the recipients of a group message). */
  top?: React.ReactNode
  /** Drawn behind the text (chips of a "/" command, "@" names). */
  backdrop?: React.ReactNode
  textareaRef?: React.Ref<HTMLTextAreaElement>
  textarea: Omit<React.ComponentProps<typeof Textarea>, 'ref' | 'className' | 'minRows'> & Record<`data-${string}`, string>
  /** The attach button (a file picker): none = no button. */
  onFiles?: (files: File[]) => void
  attachLabel?: string
  attachTestId?: string
  /** Tools after the attach button (model, compaction gauge, poll...). */
  toolbar?: React.ReactNode
  /** Actions before the microphone (Stop, new conversation...). */
  actions?: React.ReactNode
  voice?: React.ReactNode
  send: SendProps
  /** Why nothing can be sent now (uploads, a failed file...): next to Send, under the box on a phone. */
  reason?: string | null
  /** Shown instead of the text and its bar (a paused agent, a group not ready). */
  closed?: React.ReactNode
  /** Props of the box itself (data-tour, drop handlers...). */
  boxProps?: React.HTMLAttributes<HTMLDivElement> & Record<`data-${string}`, string>
  dimmed?: boolean
  /** A narrow panel (Team beside another page): less padding, no reading width. */
  compact?: boolean
  className?: string
  /** The width of the box (default: the reading width of a session). */
  widthClassName?: string
}

export function MessageBox(p: MessageBoxProps) {
  const t = useT()
  const fileInput = React.useRef<HTMLInputElement>(null)
  const { className: boxClass, ...boxRest } = p.boxProps || {}
  // New files go at the end of the strip: keep them in view.
  const attBox = React.useRef<HTMLDivElement>(null)
  const n = p.atts?.length || 0
  const donePaths = React.useMemo(() => (p.atts || []).flatMap((a) => (a.path && !a.error ? [a.path] : [])), [p.atts])
  const attCount = React.useRef(n)
  React.useEffect(() => {
    if (n > attCount.current) attBox.current?.scrollTo({ top: attBox.current.scrollHeight, behavior: 'smooth' })
    attCount.current = n
  }, [n])
  return (
    <div className={cn('shrink-0', p.compact ? 'p-2' : 'px-3 pt-1 pb-3 max-md:pb-[calc(0.5rem+var(--safe-bottom-ui))]', p.className)}>
      <div className={cn('mx-auto w-full', !p.compact && (p.widthClassName || 'max-w-(--mx-read,860px)'))}>
        {p.above}
        <div
          {...boxRest}
          // A click on the box around the text (its margins, the empty part of its bar) puts the caret in the text
          // instead of selecting nothing or the page.
          onMouseDown={(e) => {
            boxRest.onMouseDown?.(e)
            if (e.defaultPrevented || e.button !== 0 || p.closed) return
            const ta = e.currentTarget.querySelector('textarea')
            if (!ta || e.target === ta) return
            // something of its own in the box (a button, a file, a menu): not the text (the page around does not count)
            const own = (e.target as Element).closest('button, a, input, select, textarea, label, [role], [contenteditable], [data-testid$="attachments"]')
            if (own && own !== e.currentTarget && e.currentTarget.contains(own)) return
            e.preventDefault()
            if (document.activeElement !== ta) {
              ta.focus({ preventScroll: true })
              ta.setSelectionRange(ta.value.length, ta.value.length)
            }
          }}
          className={cn(
            'mx-lg relative z-10 rounded-xl border bg-card shadow-xs transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/20',
            p.dimmed && 'opacity-80',
            boxClass,
          )}
        >
          {p.menu}
          {p.closed ? (
            <div className="px-3.5 py-3 text-sm text-muted-foreground">{p.closed}</div>
          ) : (
            <>
              {p.top}
              {n > 0 && (
                // Many files: a small scrolling strip (two rows) instead of a box that eats the conversation.
                <div ref={attBox} data-testid={p.attsTestId || 'composer-attachments'} className="flex max-h-[6.75rem] flex-wrap gap-1.5 overflow-y-auto overscroll-contain px-2.5 pt-2.5 [scrollbar-width:thin]">
                  {p.atts!.map((a) => (
                    <AttachmentChip key={a.lid} att={a} list={donePaths} onRemove={() => p.onRemoveAtt?.(a.lid)} />
                  ))}
                </div>
              )}
              {p.backdrop}
              <Textarea
                ref={p.textareaRef}
                minRows={1}
                maxRows={12}
                {...p.textarea}
                className="relative border-0 bg-transparent px-3.5 pt-3 pb-1 shadow-none focus-visible:ring-0 dark:bg-transparent"
              />
              <div className="@container flex min-w-0 flex-wrap items-center gap-1 px-1.5 pb-1.5">
                {p.onFiles && (
                  <>
                    <input
                      ref={fileInput}
                      type="file"
                      multiple
                      hidden
                      onChange={(e) => {
                        const files = Array.from(e.target.files || [])
                        e.target.value = ''
                        if (files.length) p.onFiles!(files)
                      }}
                    />
                    <Tooltip content={p.attachLabel || t('sessions.composer.attach')}>
                      <Button variant="ghost" size="icon-sm" aria-label={p.attachLabel || t('sessions.composer.attach')} onClick={() => fileInput.current?.click()} data-testid={p.attachTestId}>
                        <Paperclip />
                      </Button>
                    </Tooltip>
                  </>
                )}
                {p.toolbar}
                <div className="ml-auto flex min-w-0 items-center gap-1.5 max-md:@max-md:gap-1">
                  {p.reason && <span className="truncate text-[11px] text-muted-foreground max-sm:hidden">{p.reason}</span>}
                  {p.actions}
                  {p.voice}
                  <Tooltip content={p.send.label}>
                    <Button
                      size="icon-sm"
                      aria-label={p.send.label}
                      disabled={p.send.disabled}
                      onClick={p.send.onClick}
                      data-testid={p.send.testId}
                      className="rounded-lg max-md:size-11 max-md:rounded-full max-md:[&_svg]:size-5 max-md:@max-md:size-10!"
                    >
                      {p.send.busy ? <Spinner className="size-4" /> : p.send.icon || <ArrowUp />}
                    </Button>
                  </Tooltip>
                </div>
              </div>
            </>
          )}
        </div>
        {p.reason && !p.closed && <p className="mt-1 truncate text-[11px] text-muted-foreground sm:hidden">{p.reason}</p>}
      </div>
    </div>
  )
}

/** The Stop button of a box whose turn is running (same size as Send). */
export function StopButton({ onClick, busy, label }: { onClick: () => void; busy?: boolean; label: string }) {
  return (
    <Tooltip content={label}>
      <Button variant="outline" size="icon-sm" aria-label={label} onClick={onClick} loading={busy} className="max-md:size-11 max-md:rounded-full max-md:@max-md:size-10!">
        <Square className="fill-current" />
      </Button>
    </Tooltip>
  )
}
