// What an agent's page and a group's page share: the back link on a phone, the loading / not-found page, a time,
// a side sheet, answers folded past FOLD_CHARS, the link to a run, the plumbing of the message box.
import * as React from 'react'
import { Link } from 'react-router'
import { ArrowLeft, PlayCircle, type LucideIcon } from 'lucide-react'
import type { Components } from 'react-markdown'
import { useLang, useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { agentRunRoute } from '@/lib/queries'
import { fmtDate, fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { useCompact } from '@/stores/media'
import { Button, EmptyState, Sensitive, Sheet, SheetBody, SheetContent, SheetDescription, SheetHeader, SheetTitle, Skeleton } from '@/components/ui'
import { Page } from '@/components/shell/Page'
import { MessageMedia } from '@/pages/sessions/Items'
import { AnswerText } from './answer'

/** On a phone the page is full screen: back to the list (on a computer the list stays on the left). */
export function useBack() {
  const t = useT()
  return useCompact() ? (
    <Button asChild variant="ghost" size="icon-sm" aria-label={t('agents.back')} className="-ml-1">
      <Link to="/agents">
        <ArrowLeft />
      </Link>
    </Button>
  ) : null
}

/** The page while it loads (`loading`, `head`: the height of its first block), or when it cannot be read. */
export function PageFallback({ name, back, loading, head, icon, title, error, retry }: {
  name: string; back: React.ReactNode; loading: boolean; head: string; icon: LucideIcon; title: string; error: unknown; retry: () => void
}) {
  const t = useT()
  if (loading)
    return (
      <Page title={name} leading={back} width="wide">
        <Skeleton className={cn(head, 'rounded-xl')} />
        <Skeleton className="mt-4 h-80 rounded-xl" />
      </Page>
    )
  return (
    <Page title={name} leading={back}>
      <EmptyState
        icon={icon}
        tone="error"
        title={title}
        description={errorMessage(error)}
        action={
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => retry()}>
              {t('common.retry')}
            </Button>
            <Button asChild size="sm">
              <Link to="/agents">{t('agents.backToList')}</Link>
            </Button>
          </div>
        }
      />
    </Page>
  )
}

export function When({ at }: { at: number }) {
  const lang = useLang()
  return (
    <time className="text-[11px] text-muted-foreground tabular-nums" dateTime={new Date(at * 1000).toISOString()} title={fmtDate(at, lang)}>
      {fmtRelative(at, lang)}
    </time>
  )
}

export function SideSheet({ open, onOpenChange, title, description, className, bodyClassName, testid, children }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: string; className?: string; bodyClassName?: string; testid?: string
  children: React.ReactNode
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className={className} data-testid={testid}>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {description && <SheetDescription>{description}</SheetDescription>}
        </SheetHeader>
        <SheetBody className={bodyClassName}>{children}</SheetBody>
      </SheetContent>
    </Sheet>
  )
}

/** An answer longer than this is folded (the first lines and "Read all"). */
const FOLD_CHARS = 700

/** `folded`: the answer is cut (until "Read all"); `toggle`: that button, when the text is long and `foldable`. */
export function useFold(text: string | undefined, foldable = true) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  const long = foldable && (text || '').length > FOLD_CHARS
  const toggle = long && (
    <button type="button" className="text-xs text-primary hover:underline pointer-coarse:min-h-10" onClick={() => setOpen((o) => !o)}>
      {open ? t('agents.conv.readLess') : t('agents.conv.readMore')}
    </button>
  )
  return { folded: long && !open, toggle }
}

/** What an agent wrote (folded or not), then the pictures and videos it names. */
export function FoldedAnswer({ text, folded, components }: { text: string; folded: boolean; components?: Components }) {
  return (
    <>
      <div className={cn('relative min-w-0 text-sm', folded && 'max-h-64 overflow-hidden')} data-quote>
        <Sensitive block>
          <AnswerText text={text} components={components} />
        </Sensitive>
        {folded && <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-card" aria-hidden />}
      </div>
      <Sensitive block>
        <MessageMedia text={text} />
      </Sensitive>
    </>
  )
}

/** "Open the run": the turn's session, in place. */
export function RunLink({ path, sid, testid, className }: { path: string; sid: string; testid: string; className?: string }) {
  const t = useT()
  return (
    <Link to={agentRunRoute(path, sid)} className={cn('inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-primary hover:underline pointer-coarse:min-h-10', className)} data-testid={testid}>
      <PlayCircle className="size-3" /> {t('agents.thread.openRun')}
    </Link>
  )
}

/** Reading the page = its results are read (again when a new one comes in while it is open). */
export function useMarkSeen(mutate: (v: { path: string }) => void, unread: number, path: string) {
  React.useEffect(() => {
    if (unread > 0) mutate({ path })
  }, [unread, path, mutate])
}

/** The box's textarea: a ref, and the element as state too (the chips' backdrop follows it from its first render, a
 *  restored draft). The caret goes to `placeAt` as soon as the new text is in the box (before the next key is typed);
 *  `putText`: "Paste as text" puts a paste back there. */
export function useBoxInput(text: string, setText: React.Dispatch<React.SetStateAction<string>>) {
  const input = React.useRef<HTMLTextAreaElement>(null)
  const [inputEl, setInputEl] = React.useState<HTMLTextAreaElement | null>(null)
  const setInput = React.useCallback((el: HTMLTextAreaElement | null) => {
    input.current = el
    setInputEl(el)
  }, [])
  const placeAt = React.useRef<number | null>(null)
  const putText = (pasted: string, start: number, end: number) =>
    setText((cur) => {
      const from = Math.min(start, cur.length)
      placeAt.current = from + pasted.length
      return cur.slice(0, from) + pasted + cur.slice(Math.min(end, cur.length))
    })
  React.useLayoutEffect(() => {
    const el = input.current
    if (placeAt.current == null || !el) return
    el.focus()
    el.setSelectionRange(placeAt.current, placeAt.current)
    placeAt.current = null
  }, [text])
  return { input, inputEl, setInput, placeAt, putText }
}

/** A stable handler that runs `fn` of the last render. The voice button hands a dictation over with the handler of
 *  the render where recording stopped: through this one, what was typed or attached meanwhile is neither lost nor
 *  sent stale. */
export function useLatest<A extends unknown[]>(fn: (...args: A) => void) {
  const live = React.useRef(fn)
  live.current = fn
  return React.useCallback((...args: A) => live.current(...args), [])
}
