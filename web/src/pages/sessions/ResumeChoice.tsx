import * as React from 'react'
import { CircleHelp, History, Layers, Sparkles } from 'lucide-react'
import { Button, Sensitive } from '@/components/ui'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { CloseButton } from '@/features/composer/MessageBox'
import { loadGroups, useT } from '@/i18n'
import type { Session } from '@/lib/types'

/** What the user chose for a message coming back to a big session whose prompt cache expired (Session.resume_at):
 * the summary written for it (what the server does by itself), a new empty session, or the whole history. */
export type ResumeChoice = 'summary' | 'fresh' | 'keep'

/** True when a message sent now to this session would get a summary first: the composer asks before (the server
 * gives no resume_at when Settings -> Claude -> "Ask before resuming" is off). */
export function resumeAsks(s: Session | undefined, running: boolean): boolean {
  return !!s && !running && !!s.resume_at && Date.now() / 1000 >= s.resume_at
}

type Ask = { text: string; away: number; tokens: number; resolve: (c: ResumeChoice | null) => void }

/** `ask(session, text)` holds the message in a card tucked on top of the composer (like the waiting messages) until
 * the user picks; null: closed, the message comes back in the box. `card` goes to the Composer's `held`. */
export function useResumeChoice() {
  const [ask, setAsk] = React.useState<Ask | null>(null)
  const open = React.useCallback(async (s: Session, text: string) => {
    await loadGroups(['resume']).catch(() => undefined)
    const since = s.updated || 0 // the end of its last turn (a rename moves it too: close enough for the line)
    return new Promise<ResumeChoice | null>((resolve) =>
      setAsk((prev) => {
        prev?.resolve(null)
        return { text, away: Math.max(0, Date.now() / 1000 - since), tokens: s.context_tokens || 0, resolve }
      }),
    )
  }, [])
  const choose = (c: ResumeChoice | null) => {
    ask?.resolve(c)
    setAsk(null)
  }
  return [open, ask ? <ResumeCard ask={ask} onChoose={choose} /> : null] as const
}

function ResumeCard({ ask, onChoose }: { ask: Ask; onChoose: (c: ResumeChoice | null) => void }) {
  const t = useT()
  const away = ask.away >= 5400 ? t('resume.awayHours', { n: Math.round(ask.away / 3600) }) : t('resume.awayMinutes', { n: Math.max(1, Math.round(ask.away / 60)) })
  const small = 'h-7 px-2 text-xs max-md:h-8 pointer-coarse:h-10 max-md:pointer-coarse:h-10'
  const [help, setHelp] = React.useState(false)
  const helpOpen = React.useRef(false)
  helpOpen.current = help
  React.useEffect(() => {
    // capture: seen before the explanation closes on the same Escape (that one only closes the explanation)
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && !helpOpen.current && onChoose(null)
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [onChoose])
  const k = Math.round(ask.tokens / 1000)
  return (
    <div aria-live="polite" data-testid="resume-card">
      <div className="flex items-center gap-1.5 px-3 pt-2 text-xs text-muted-foreground">
        <History className="size-3.5 shrink-0 text-primary" />
        <span className="min-w-0 truncate">{t('resume.line', { away, k })}</span>
        <Popover open={help} onOpenChange={setHelp}>
          <PopoverTrigger
            aria-label={t('resume.why')}
            data-testid="resume-help"
            className="flex size-6 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none pointer-coarse:size-10"
          >
            <CircleHelp className="size-3.5" />
          </PopoverTrigger>
          <PopoverContent align="start" className="grid w-80 max-w-[calc(100vw-1.5rem)] gap-2 p-3 text-xs leading-relaxed text-muted-foreground">
            <p className="text-sm font-medium text-foreground">{t('resume.why')}</p>
            <p>{t('resume.whyCache', { k })}</p>
            <ul className="grid gap-1.5">
              <li><span className="font-medium text-foreground">{t('resume.summary')}</span> — {t('resume.summaryTip')}</li>
              <li><span className="font-medium text-foreground">{t('resume.fresh')}</span> — {t('resume.freshTip')}</li>
              <li><span className="font-medium text-foreground">{t('resume.keep')}</span> — {t('resume.keepTip')}</li>
            </ul>
            <p>{t('resume.whyOff')}</p>
          </PopoverContent>
        </Popover>
        <CloseButton label={t('resume.cancel')} onClick={() => onChoose(null)} />
      </div>
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-3 pt-1 pb-5">
        <p className="line-clamp-2 min-w-[10rem] flex-1 text-[14px] leading-relaxed break-words text-foreground">
          <Sensitive length={12}>{ask.text}</Sensitive>
        </p>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          <Button size="sm" variant="ghost" className={small} onClick={() => onChoose('keep')} title={t('resume.keepTip')}>
            <History className="size-3.5" /> {t('resume.keep')}
          </Button>
          <Button size="sm" variant="ghost" className={small} onClick={() => onChoose('fresh')} title={t('resume.freshTip')}>
            <Layers className="size-3.5" /> {t('resume.fresh')}
          </Button>
          <Button size="sm" className={small} onClick={() => onChoose('summary')} title={t('resume.summaryTip')} autoFocus>
            <Sparkles className="size-3.5" /> {t('resume.summary')}
          </Button>
        </span>
      </div>
    </div>
  )
}
