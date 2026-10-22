// /welcome — first-run wizard. Resumable: the current step lives in ?step= and localStorage.
// Every step reuses the components of Settings (src/features/*).
import * as React from 'react'
import { store as lsStore } from '@/lib/utils'
import { useNavigate, useSearchParams } from 'react-router'
import { ArrowLeft, ArrowRight, BookOpen, Check, Clock, FolderOpen, ListChecks, MessagesSquare, Send, type LucideIcon } from 'lucide-react'
import { useClaudeStatus, useCompleteOnboarding, useOnboarding, useProfile, useRegister, useSaveLicense, useSaveProfile, useSaveRegister, useSaveSettings, useSettings } from '@/lib/queries'
import { browserTimezone } from '@/lib/timezones'
import { useUI } from '@/stores/ui'
import { cn } from '@/lib/utils'
import { useT, type TKey } from '@/i18n'
import type { Language, OnboardingState } from '@/lib/types'
import { Badge, Button, Checkbox, Input, Label, Sensitive, Skeleton } from '@/components/ui'
import { errorMessage } from '@/lib/api'
import { LogoMark } from '@/components/shell/Logo'
import { useDocumentTitle } from '@/components/shell/Page'
import { RegionFields } from '@/features/general/RegionFields'
import { ClaudeConnect } from '@/features/claude/ClaudeConnect'
import { ClaudeDefaults } from '@/features/claude/ClaudeDefaults'
import { CreateProjectTopic } from '@/features/workspace/CreateProjectTopic'
import { TelegramSetup } from '@/features/telegram/TelegramSetup'
import { BackupSetup, BackupWhy } from '@/features/backup/BackupSetup'
import { Callout } from '@/features/common'
import { VoiceQuickSetup } from '@/features/voice/VoiceSetup'
import { requestTourAfterOnboarding } from '@/tour/store'
import { ImportWizard } from '@/features/import/ImportWizard'
import { PackChooser } from '@/features/packs/PackPicker'
import { RegisterFields, validEmail, type RegisterValues } from '@/features/profile/Register'
import { LicenseKeyField, WhoNeedsAKey, validKey } from '@/features/license/LicenseKey'

type StepId = 'language' | 'profile' | 'claude' | 'import' | 'workspace' | 'telegram' | 'backup' | 'done'
const STEPS: { id: StepId; label: TKey; optional?: boolean }[] = [
  { id: 'language', label: 'onb.step.language' },
  { id: 'profile', label: 'onb.step.profile', optional: true },
  { id: 'claude', label: 'onb.step.claude' },
  { id: 'import', label: 'onb.step.import', optional: true },
  { id: 'workspace', label: 'onb.step.workspace' },
  { id: 'telegram', label: 'onb.step.telegram', optional: true },
  { id: 'backup', label: 'onb.step.backup', optional: true },
  { id: 'done', label: 'onb.step.done' },
]
const LS_KEY = 'mx-onboarding-step'

function stepDone(id: StepId, o: OnboardingState | undefined): boolean {
  if (!o) return false
  if (id === 'language') return true
  if (id === 'done') return o.completed
  return !!o.steps[id as keyof OnboardingState['steps']]
}

export default function OnboardingPage() {
  const t = useT()
  useDocumentTitle(t('onb.title'))
  const [params, setParams] = useSearchParams()
  const { data: onboarding } = useOnboarding()
  const fromUrl = params.get('step') as StepId | null
  const stored = lsStore.get(LS_KEY) as StepId | null
  const current: StepId = STEPS.some((s) => s.id === fromUrl) ? fromUrl! : STEPS.some((s) => s.id === stored) ? stored! : 'language'
  const idx = STEPS.findIndex((s) => s.id === current)
  const top = React.useRef<HTMLDivElement>(null)

  const go = React.useCallback(
    (id: StepId) => {
      lsStore.set(LS_KEY, id)
      setParams({ step: id })
      top.current?.focus({ preventScroll: true })
      window.scrollTo({ top: 0 })
    },
    [setParams],
  )
  const next = () => go(STEPS[Math.min(idx + 1, STEPS.length - 1)].id)
  const back = () => go(STEPS[Math.max(idx - 1, 0)].id)

  return (
    <div className="min-h-dvh bg-background pt-[var(--safe-top)] pb-[var(--safe-bottom)]">
      <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 h-80 bg-[radial-gradient(50rem_20rem_at_30%_-20%,color-mix(in_oklch,var(--primary)_12%,transparent),transparent_70%)]" />
      <div className="relative mx-auto grid max-w-5xl gap-8 px-4 py-6 md:grid-cols-[220px_1fr] md:gap-12 md:px-8 md:py-12">
        {/* Stepper */}
        <aside className="md:sticky md:top-12 md:self-start">
          <div className="mb-6 flex items-center gap-2.5 md:mb-10">
            <LogoMark />
            <span className="text-[15px] font-semibold tracking-tight">Harness Maxxing</span>
          </div>
          {/* Mobile: compact progress */}
          <div className="md:hidden">
            <div className="mb-2 flex items-center justify-between text-[13px]">
              <span className="font-medium">{t(STEPS[idx].label)}</span>
              <span className="text-muted-foreground tabular-nums">{t('onb.stepOf', { n: idx + 1, total: STEPS.length })}</span>
            </div>
            <div className="grid gap-1" style={{ gridTemplateColumns: `repeat(${STEPS.length}, minmax(0, 1fr))` }}>
              {STEPS.map((s, i) => (
                <span key={s.id} className={cn('h-1 rounded-full', i <= idx ? 'bg-primary' : 'bg-muted')} />
              ))}
            </div>
          </div>
          {/* Desktop: vertical stepper */}
          <nav aria-label={t('onb.progress')} className="max-md:hidden">
            <ol className="grid gap-1">
              {STEPS.map((s, i) => {
                const done = s.id === 'language' ? idx > 0 : s.id !== 'done' && stepDone(s.id, onboarding)
                const active = i === idx
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      onClick={() => go(s.id)}
                      aria-current={active ? 'step' : undefined}
                      className={cn(
                        'group flex w-full items-center gap-3 rounded-md px-2 py-2 text-left text-sm outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring',
                        active ? 'font-medium text-foreground' : 'text-muted-foreground',
                      )}
                    >
                      <span
                        className={cn(
                          'flex size-6 shrink-0 items-center justify-center rounded-full border text-xs font-semibold tabular-nums transition-colors',
                          active && 'border-primary bg-primary text-primary-foreground',
                          done && !active && 'border-success/40 bg-success/15 text-success',
                        )}
                      >
                        {done && !active ? <Check className="size-3.5" strokeWidth={3} /> : i + 1}
                      </span>
                      <span className="flex-1">{t(s.label)}</span>
                      {s.optional && <span className="text-[11px] text-muted-foreground">{t('onb.optional')}</span>}
                    </button>
                  </li>
                )
              })}
            </ol>
          </nav>
        </aside>

        {/* Step content */}
        <main ref={top} tabIndex={-1} className="min-w-0 outline-none" key={current}>
          <div className="animate-in">
            {current === 'language' && <LanguageStep onNext={next} />}
            {current === 'profile' && <ProfileStep onNext={next} onBack={back} />}
            {current === 'claude' && <ClaudeStep onNext={next} onBack={back} />}
            {current === 'import' && <ImportStep onNext={next} onBack={back} />}
            {current === 'workspace' && <WorkspaceStep onNext={next} onBack={back} />}
            {current === 'telegram' && <TelegramStep onNext={next} onBack={back} done={stepDone('telegram', onboarding)} />}
            {current === 'backup' && <BackupStep onNext={next} onBack={back} done={stepDone('backup', onboarding)} />}
            {current === 'done' && <DoneStep onBack={back} onboarding={onboarding} />}
          </div>
        </main>
      </div>
    </div>
  )
}

function StepHeader({ step, title, description }: { step: StepId; title: string; description?: React.ReactNode }) {
  const t = useT()
  const s = STEPS.find((x) => x.id === step)!
  return (
    <div className="mb-8 grid gap-2">
      <div className="flex items-center gap-2 text-[13px] text-muted-foreground max-md:hidden">
        {t('onb.stepOf', { n: STEPS.indexOf(s) + 1, total: STEPS.length })}
        {s.optional && <Badge variant="muted">{t('onb.optional')}</Badge>}
      </div>
      <h1 className="text-2xl font-semibold tracking-tight text-balance md:text-[28px]">{title}</h1>
      {description && <p className="max-w-2xl text-[15px] text-muted-foreground">{description}</p>}
    </div>
  )
}

function StepFooter({ onBack, onNext, nextLabel, nextDisabled, loading, onSkip, skipLabel }: { onBack?: () => void; onNext?: () => void; nextLabel?: string; nextDisabled?: boolean; loading?: boolean; onSkip?: () => void; skipLabel?: string }) {
  const t = useT()
  return (
    <div className="mt-10 flex flex-col-reverse gap-3 border-t pt-6 sm:flex-row sm:items-center">
      {onBack && (
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft /> {t('common.back')}
        </Button>
      )}
      <div className="flex-1" />
      {onSkip && (
        <Button variant="outline" onClick={onSkip}>
          {skipLabel || t('onb.skip')}
        </Button>
      )}
      {onNext && (
        <Button onClick={onNext} disabled={nextDisabled} loading={loading}>
          {nextLabel || t('common.continue')} <ArrowRight />
        </Button>
      )}
    </div>
  )
}

function LanguageStep({ onNext }: { onNext: () => void }) {
  const t = useT()
  const { data: settings } = useSettings()
  const save = useSaveSettings()
  const language = useUI((s) => s.language)
  const setLanguage = useUI((s) => s.setLanguage)
  const [tz, setTz] = React.useState<string | null>(null)
  React.useEffect(() => {
    if (settings && tz === null) setTz(!settings.timezone || settings.timezone === 'UTC' ? browserTimezone() : settings.timezone)
  }, [settings, tz])
  return (
    <>
      <StepHeader step="language" title={t('onb.language.title')} description={t('onb.language.desc')} />
      {tz === null ? (
        <div className="grid gap-5">
          <Skeleton className="h-16 w-64" />
          <Skeleton className="h-16" />
        </div>
      ) : (
        <div className="max-w-lg">
          <RegionFields language={language} timezone={tz} onLanguage={(l: Language) => setLanguage(l)} onTimezone={setTz} />
        </div>
      )}
      <StepFooter
        loading={save.isPending}
        nextDisabled={tz === null}
        onNext={() => save.mutate({ language, timezone: tz || 'UTC' }, { onSuccess: onNext })}
      />
    </>
  )
}

function ProfileStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const t = useT()
  const { data: profile } = useProfile()
  const { data: reg } = useRegister()
  const saveProfile = useSaveProfile()
  const saveRegister = useSaveRegister()
  const [name, setName] = React.useState<string | null>(null)
  const [v, setV] = React.useState<RegisterValues | null>(null)
  const saveLicense = useSaveLicense()
  const [keyOpen, setKeyOpen] = React.useState(false)
  const [key, setKey] = React.useState('')
  const [keyError, setKeyError] = React.useState('')
  React.useEffect(() => {
    if (profile && name === null) setName(profile.name)
  }, [profile, name])
  React.useEffect(() => {
    // first visit: the anonymous counter is checked (the user unchecks it here); afterwards, what was saved
    if (reg && v === null) setV({ email: reg.email, news: reg.news, count: reg.asked ? reg.count : true })
  }, [reg, v])
  const ready = profile && reg && name !== null && v !== null
  const go = async () => {
    if (!ready) return
    if (name.trim() !== profile.name) await saveProfile.mutateAsync({ ...profile, name: name.trim().slice(0, 32) })
    await saveRegister.mutateAsync({ ...v, email: v.email.trim(), asked: true })
    if (key.trim()) {
      try {
        await saveLicense.mutateAsync(key.trim())
      } catch (e) {
        setKeyError(errorMessage(e))
        return
      }
    }
    onNext()
  }
  return (
    <>
      <StepHeader step="profile" title={t('onb.profile.title')} description={t('onb.profile.desc')} />
      {!ready ? (
        <div className="grid gap-5">
          <Skeleton className="h-16 w-64" />
          <Skeleton className="h-28" />
        </div>
      ) : (
        <div className="grid max-w-lg gap-5">
          <div className="grid gap-1.5">
            <Label htmlFor="onb-pseudo">{t('profile.name')}</Label>
            <Input id="onb-pseudo" value={name} maxLength={32} placeholder={t('profile.namePlaceholder')} onChange={(e) => setName(e.target.value)} className="max-w-sm" />
            <p className="text-xs text-muted-foreground">{t('onb.profile.pseudoDesc')}</p>
          </div>
          <RegisterFields v={v} onChange={setV} />
          <p className="text-xs text-muted-foreground">{t('register.privacy')}</p>
          <div className="grid gap-3 border-t pt-4">
            <label className="flex items-start gap-2.5 text-sm">
              <Checkbox className="mt-0.5" checked={keyOpen} onCheckedChange={(c) => (setKeyOpen(c === true), c !== true && (setKey(''), setKeyError('')))} />
              <span>
                {t('license.onbToggle')}
                <span className="block text-xs text-muted-foreground">{t('license.onbToggleDesc')}</span>
              </span>
            </label>
            {keyOpen && (
              <div className="grid gap-3 pl-6">
                <WhoNeedsAKey />
                <LicenseKeyField value={key} onChange={(k) => (setKey(k), setKeyError(''))} error={keyError} />
              </div>
            )}
          </div>
        </div>
      )}
      <StepFooter onBack={onBack} onNext={go} loading={saveProfile.isPending || saveRegister.isPending || saveLicense.isPending} nextDisabled={!ready || !validEmail(v.email) || (!!key.trim() && !validKey(key))} />
    </>
  )
}

function ClaudeStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const t = useT()
  const { data: s } = useClaudeStatus()
  const ok = !!s?.auth.ok
  return (
    <>
      <StepHeader step="claude" title={t('onb.claude.title')} description={t('onb.claude.desc')} />
      <div className="grid gap-10">
        <ClaudeConnect />
        <section className={cn('grid gap-4 transition-opacity', !ok && 'pointer-events-none opacity-50')} aria-disabled={!ok}>
          <div className="grid gap-1">
            <h2 className="text-[15px] font-semibold">{t('onb.claude.defaults')}</h2>
            <p className="text-sm text-muted-foreground">{t('onb.claude.defaultsDesc')}</p>
          </div>
          <ClaudeDefaults />
        </section>
      </div>
      <StepFooter onBack={onBack} onNext={onNext} onSkip={ok ? undefined : onNext} skipLabel={t('onb.claude.later')} nextDisabled={!ok} />
    </>
  )
}

function WorkspaceStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const t = useT()
  const [own, setOwn] = React.useState(false)
  const [created, setCreated] = React.useState<string | null>(null)
  return (
    <>
      <StepHeader step="workspace" title={t('onb.workspace.title')} description={t('onb.workspace.desc')} />
      <div className="grid gap-6">
        <PackChooser
          onDone={onNext}
          footer={(next, busy) => (
            <>
              <div className="grid gap-3">
                {created ? (
                  <Callout tone="success" title={t('onb.workspace.created')}>
                    <span className="font-mono">
                      <Sensitive>{created}</Sensitive>
                    </span>
                  </Callout>
                ) : own ? (
                  <div className="max-w-lg">
                    <CreateProjectTopic onCreated={(tp) => setCreated(tp.path)} />
                  </div>
                ) : (
                  <button type="button" className="w-fit text-sm font-medium text-primary hover:underline" onClick={() => setOwn(true)}>
                    {t('onb.workspace.own')}
                  </button>
                )}
              </div>
              <StepFooter onBack={onBack} onNext={next} loading={busy} />
            </>
          )}
        />
      </div>
    </>
  )
}

function ImportStep({ onNext, onBack }: { onNext: () => void; onBack: () => void }) {
  const t = useT()
  const [done, setDone] = React.useState(false)
  return (
    <>
      <StepHeader step="import" title={t('onb.import.title')} description={t('onb.import.desc')} />
      <ImportWizard compact autoFinish onDone={() => setDone(true)} />
      <StepFooter onBack={onBack} onNext={done ? onNext : undefined} onSkip={done ? undefined : onNext} skipLabel={done ? undefined : t('onb.import.skip')} />
    </>
  )
}

function TelegramStep({ onNext, onBack, done }: { onNext: () => void; onBack: () => void; done: boolean }) {
  const t = useT()
  return (
    <>
      <StepHeader step="telegram" title={t('onb.telegram.title')} description={t('onb.telegram.desc')} />
      <TelegramSetup />
      <div className="mt-6">
        <VoiceQuickSetup />
      </div>
      <StepFooter onBack={onBack} onNext={done ? onNext : undefined} onSkip={done ? undefined : onNext} />
    </>
  )
}

function BackupStep({ onNext, onBack, done }: { onNext: () => void; onBack: () => void; done: boolean }) {
  const t = useT()
  return (
    <>
      <StepHeader step="backup" title={t('onb.backup.title')} description={t('onb.backup.desc')} />
      <div className="grid gap-6">
        <BackupWhy />
        <BackupSetup />
      </div>
      <StepFooter onBack={onBack} onNext={done ? onNext : undefined} onSkip={done ? undefined : onNext} />
    </>
  )
}

const TOUR: { icon: LucideIcon; title: TKey; desc: TKey }[] = [
  { icon: MessagesSquare, title: 'nav.sessions', desc: 'onb.tour.sessions' },
  { icon: FolderOpen, title: 'nav.files', desc: 'onb.tour.files' },
  { icon: ListChecks, title: 'nav.tasks', desc: 'onb.tour.tasks' },
  { icon: Clock, title: 'nav.crons', desc: 'onb.tour.crons' },
  { icon: Send, title: 'settings.telegram', desc: 'onb.tour.telegram' },
  { icon: BookOpen, title: 'nav.docs', desc: 'onb.tour.docs' },
]

function DoneStep({ onBack, onboarding }: { onBack: () => void; onboarding: OnboardingState | undefined }) {
  const t = useT()
  const navigate = useNavigate()
  const complete = useCompleteOnboarding()
  const rows: { label: TKey; ok: boolean; optional?: boolean }[] = [
    { label: 'onb.summary.password', ok: !!onboarding?.steps.password },
    { label: 'onb.summary.claude', ok: !!onboarding?.steps.claude },
    { label: 'onb.summary.workspace', ok: !!onboarding?.steps.workspace },
    { label: 'onb.summary.telegram', ok: !!onboarding?.steps.telegram, optional: true },
    { label: 'onb.summary.backup', ok: !!onboarding?.steps.backup, optional: true },
  ]
  return (
    <>
      <StepHeader step="done" title={t('onb.done.title')} description={t('onb.done.desc')} />
      <div className="grid gap-8">
        <ul className="grid gap-2 rounded-xl border p-4 sm:grid-cols-2">
          {rows.map((r) => (
            <li key={r.label} className="flex items-center gap-2.5 text-sm">
              <span className={cn('flex size-5 items-center justify-center rounded-full', r.ok ? 'bg-success/15 text-success' : 'bg-muted text-muted-foreground')}>
                {r.ok ? <Check className="size-3.5" strokeWidth={3} /> : <span className="size-1.5 rounded-full bg-current" />}
              </span>
              <span className={cn(!r.ok && 'text-muted-foreground')}>{t(r.label)}</span>
              {!r.ok && <span className="text-xs text-muted-foreground">{r.optional ? t('onb.summary.skipped') : t('onb.summary.todo')}</span>}
            </li>
          ))}
        </ul>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {TOUR.map((c) => (
            <div key={c.title} className="rounded-xl border bg-card p-4">
              <c.icon className="mb-3 size-5 text-primary" strokeWidth={1.8} />
              <div className="text-sm font-medium">{t(c.title)}</div>
              <p className="mt-1 text-[13px] text-muted-foreground">{t(c.desc)}</p>
            </div>
          ))}
        </div>
      </div>
      <StepFooter
        onBack={onBack}
        loading={complete.isPending}
        nextLabel={t('onb.done.finish')}
        onNext={() =>
          complete.mutate(undefined, {
            onSuccess: () => {
              lsStore.remove(LS_KEY)
              requestTourAfterOnboarding()
              navigate('/sessions', { replace: true })
            },
          })
        }
      />
    </>
  )
}
