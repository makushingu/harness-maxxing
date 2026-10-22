import * as React from 'react'
import { Check, Download, Laptop, Play, RefreshCw, Square, Trash2, Unlink, X } from 'lucide-react'
import { usePc, usePcConfirm, usePcPairing, usePcSettings, usePcStop, usePcTest, usePcUnpair, usePcWipe } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import type { PcBrowser, PcOs, PcPairing, PcStatus } from '@/lib/types'
import { useLang, useT } from '@/i18n'
import { Badge, Button, CopyButton, Segmented, StatusDot, Switch, confirm, toast } from '@/components/ui'
import { Callout, SettingRow, Steps } from '@/features/common'
import { SettingsCard } from '@/pages/settings/sections/ui'

const BROWSER_LABEL: Record<PcBrowser, string> = { brave: 'Brave', chrome: 'Chrome', edge: 'Edge', vivaldi: 'Vivaldi', opera: 'Opera', chromium: 'Chromium' }
const OS_BROWSERS: Record<PcOs, PcBrowser[]> = {
  windows: ['chrome', 'edge', 'brave', 'vivaldi', 'opera', 'chromium'],
  darwin: ['chrome', 'brave', 'edge', 'vivaldi', 'opera', 'chromium'],
  linux: ['chrome', 'chromium', 'brave', 'edge', 'vivaldi', 'opera'],
}

/** This computer's system and browser, as a first guess (the user confirms). */
function guess(): { os: PcOs; browser: PcBrowser } {
  const ua = navigator.userAgent
  const os: PcOs = /Windows/i.test(ua) ? 'windows' : /Mac OS X|Macintosh/i.test(ua) ? 'darwin' : 'linux'
  const brave = (navigator as Navigator & { brave?: unknown }).brave
  const browser: PcBrowser = brave ? 'brave' : /Edg\//.test(ua) ? 'edge' : /OPR\//.test(ua) ? 'opera' : /Vivaldi/.test(ua) ? 'vivaldi' : 'chrome'
  return { os, browser }
}

export function PcBrowserCard() {
  const t = useT()
  const { data: s } = usePc()
  const [setup, setSetup] = React.useState(false)
  if (!s || (!s.available && !s.device)) return null   // no Harness PC to download yet: nothing to set up
  const paired = !!s.device && !setup
  return (
    <div data-tour="pc-browser">
      <SettingsCard title={t('pc.title')} description={t('pc.desc')}>
        {s.candidate && <Candidate c={s.candidate} />}
        {paired ? <Paired s={s} onReinstall={() => setSetup(true)} /> : <Setup s={s} onDone={() => setSetup(false)} canCancel={!!s.device} />}
      </SettingsCard>
    </div>
  )
}

/** A PC used a download code: nothing reaches it until the user says it is theirs. */
function Candidate({ c }: { c: NonNullable<PcStatus['candidate']> }) {
  const t = useT()
  const answer = usePcConfirm()
  const os = c.os === 'windows' ? 'Windows' : c.os === 'darwin' ? 'Mac' : 'Linux'
  return (
    <Callout tone="warning" title={t('pc.candidateTitle', { name: c.name })} className="mb-4 mx-unfold">
      <p>{t('pc.candidateDesc', { os })}</p>
      {c.ip && <p className="mt-1 text-xs text-muted-foreground">{t('pc.candidateFrom', { ip: c.ip, time: new Date(c.created * 1000).toLocaleTimeString() })}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <Button
          size="sm"
          onClick={() => answer.mutate({ id: c.id, ok: true }, { onSuccess: (r) => (r.ok ? toast.success(t('pc.connected', { name: c.name })) : toast.error(t('pc.expired'))) })}
        >
          <Check /> {t('pc.candidateYes')}
        </Button>
        <Button size="sm" variant="outline" onClick={() => answer.mutate({ id: c.id, ok: false })}>
          <X /> {t('pc.candidateNo')}
        </Button>
      </div>
    </Callout>
  )
}

function Setup({ s, onDone, canCancel }: { s: PcStatus; onDone: () => void; canCancel: boolean }) {
  const t = useT()
  const g = React.useMemo(guess, [])
  const [os, setOs] = React.useState<PcOs>(g.os)
  const [browser, setBrowser] = React.useState<PcBrowser>(g.browser)
  const [autostart, setAutostart] = React.useState(true)
  const [pairing, setPairing] = React.useState<PcPairing | null>(null)
  const start = usePcPairing()
  const paired = React.useRef(s.device?.id)
  React.useEffect(() => {
    if (pairing && s.device && s.device.id !== paired.current) onDone()
  }, [s.device, pairing, onDone])
  const left = useCountdown(pairing?.expires_at)
  const prepare = () => start.mutate({ browser, os, autostart }, { onSuccess: setPairing })
  if (pairing && left > 0)
    return (
      <div className="grid grid-cols-[minmax(0,1fr)] gap-4 mx-unfold">
        <Steps
          items={[
            os === 'windows' ? t('pc.step.downloadWin') : t('pc.step.download'),
            os === 'windows' ? t('pc.step.runWin') : t('pc.step.run'),
            t('pc.step.wait', { browser: BROWSER_LABEL[browser] }),
          ]}
        />
        <div className="flex flex-wrap gap-2">
          {os === 'darwin' ? (
            <>
              <Button asChild>
                <a href={pairing.downloads['darwin-arm64']} download>
                  <Download /> {t('pc.downloadMacArm')}
                </a>
              </Button>
              <Button asChild variant="outline">
                <a href={pairing.downloads['darwin-amd64']} download>
                  <Download /> {t('pc.downloadMacIntel')}
                </a>
              </Button>
            </>
          ) : (
            <Button asChild>
              <a href={pairing.downloads[os === 'windows' ? 'windows-amd64' : 'linux-amd64']} download>
                <Download /> {t(os === 'windows' ? 'pc.downloadWin' : 'pc.downloadLinux')}
              </a>
            </Button>
          )}
        </div>
        <div className="grid grid-cols-[minmax(0,1fr)] gap-1.5">
          <p className="text-[13px] text-muted-foreground">{t(os === 'windows' ? 'pc.orCommandWin' : 'pc.orCommand')}</p>
          <div className="flex min-w-0 items-center gap-2 rounded-lg border bg-muted/40 px-3 py-2">
            <code className="min-w-0 flex-1 truncate font-mono text-xs">{pairing.commands[os]}</code>
            <CopyButton text={pairing.commands[os]} />
          </div>
        </div>
        {os === 'windows' && <Callout tone="info" title={t('pc.smartscreenTitle')}>{t('pc.smartscreen')}</Callout>}
        <p className="flex items-center gap-2 text-[13px] text-muted-foreground" aria-live="polite">
          <StatusDot tone="warn" pulse /> {t('pc.waiting', { left: clock(left) })}
        </p>
        <div className="flex gap-2">
          <Button variant="ghost" size="sm" onClick={() => setPairing(null)}>
            {t('common.back')}
          </Button>
          {canCancel && (
            <Button variant="ghost" size="sm" onClick={onDone}>
              {t('common.cancel')}
            </Button>
          )}
        </div>
      </div>
    )
  return (
    <div className="grid gap-4">
      <div className="grid gap-2">
        <p className="text-sm font-medium">{t('pc.whichOs')}</p>
        <Segmented
          value={os}
          onChange={(v) => setOs(v as PcOs)}
          aria-label={t('pc.whichOs')}
          options={[
            { value: 'windows', label: 'Windows' },
            { value: 'darwin', label: 'Mac' },
            { value: 'linux', label: 'Linux' },
          ]}
        />
      </div>
      <div className="grid gap-2">
        <p className="text-sm font-medium">{t('pc.whichBrowser')}</p>
        <div className="flex flex-wrap gap-2">
          {OS_BROWSERS[os].map((b) => (
            <Button key={b} size="sm" variant={b === browser ? 'default' : 'outline'} aria-pressed={b === browser} onClick={() => setBrowser(b)}>
              {BROWSER_LABEL[b]}
            </Button>
          ))}
        </div>
        <p className="text-[13px] text-muted-foreground">{t('pc.isolated', { browser: BROWSER_LABEL[browser] })}</p>
      </div>
      <SettingRow label={t('pc.autostart')} description={t('pc.autostartDesc')} htmlFor="pc-autostart">
        <Switch id="pc-autostart" checked={autostart} onCheckedChange={setAutostart} />
      </SettingRow>
      {pairing && left <= 0 && <Callout tone="warning" title={t('pc.expired')} className="mx-unfold" />}
      <div className="flex gap-2">
        <Button loading={start.isPending} onClick={prepare}>
          <Laptop /> {t('pc.prepare')}
        </Button>
        {canCancel && (
          <Button variant="ghost" onClick={onDone}>
            {t('common.cancel')}
          </Button>
        )}
      </div>
    </div>
  )
}

function Paired({ s, onReinstall }: { s: PcStatus; onReinstall: () => void }) {
  const t = useT()
  const lang = useLang()
  const dev = s.device!
  const stop = usePcStop()
  const test = usePcTest()
  const wipe = usePcWipe()
  const unpair = usePcUnpair()
  const save = usePcSettings()
  const tone = !s.online ? 'idle' : s.browser_running ? 'ok' : 'info'
  return (
    <div className="grid grid-cols-[minmax(0,1fr)] gap-5">
      <dl className="grid gap-4 text-sm sm:grid-cols-3">
        <div className="grid gap-1">
          <dt className="text-[13px] text-muted-foreground">{t('pc.computer')}</dt>
          <dd className="flex items-center gap-2 font-medium">
            <StatusDot tone={tone as 'ok'} pulse={s.browser_running} /> {dev.name}
          </dd>
        </div>
        <div className="grid gap-1">
          <dt className="text-[13px] text-muted-foreground">{t('pc.state')}</dt>
          <dd className="font-medium">
            {!s.online ? t('pc.offline') : s.browser_running ? t('pc.inUse', { browser: BROWSER_LABEL[dev.browser] }) : t('pc.ready')}
          </dd>
        </div>
        <div className="grid gap-1">
          <dt className="text-[13px] text-muted-foreground">{t('pc.lastUse')}</dt>
          <dd className="font-medium tabular-nums">{s.last_use ? fmtRelative(s.last_use, lang) : t('pc.never')}</dd>
        </div>
      </dl>
      {!s.mcp_registered && <Callout tone="warning" title={t('pc.mcpMissing')} className="mx-unfold" />}
      {!s.online && <Callout tone="info" title={t('pc.offlineTitle')} className="mx-unfold">{t('pc.offlineDesc')}</Callout>}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={!s.online}
          loading={test.isPending}
          onClick={() => test.mutate(undefined, { onSuccess: (r) => (r.ok ? toast.success(t('pc.testOk')) : toast.error(r.text || t('pc.testFail'))) })}
        >
          <Play /> {t('pc.test')}
        </Button>
        {s.browser_running && (
          <Button variant="outline" size="sm" onClick={() => stop.mutate()} className="mx-unfold">
            <Square /> {t('pc.stop')}
          </Button>
        )}
        <Button
          variant="ghost"
          size="sm"
          disabled={!s.online}
          onClick={async () => {
            if (await confirm({ title: t('pc.wipeConfirm'), description: t('pc.wipeDesc'), destructive: true, confirmText: t('pc.wipe') }))
              wipe.mutate(undefined, { onSuccess: () => toast.success(t('pc.wiped')) })
          }}
        >
          <Trash2 /> {t('pc.wipe')}
        </Button>
        <Button variant="ghost" size="sm" onClick={onReinstall}>
          <RefreshCw /> {t('pc.reinstall')}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-destructive"
          onClick={async () => {
            if (await confirm({ title: t('pc.unpairConfirm'), description: t('pc.unpairDesc'), destructive: true, confirmText: t('pc.unpair') })) unpair.mutate()
          }}
        >
          <Unlink /> {t('pc.unpair')}
        </Button>
      </div>
      <SettingRow label={t('pc.idle')} description={t('pc.idleDesc')}>
        <Segmented
          value={String(s.settings.idle_min)}
          onChange={(v) => save.mutate({ idle_min: Number(v) })}
          aria-label={t('pc.idle')}
          options={[5, 10, 20, 30, 60].map((m) => ({ value: String(m), label: `${m} min` }))}
        />
      </SettingRow>
      {s.actions.length > 0 && (
        <div className="grid gap-2">
          <p className="text-sm font-medium">{t('pc.recent')}</p>
          <ul className="grid grid-cols-[minmax(0,1fr)] gap-1 text-[13px]">
            {s.actions.slice(0, 6).map((a, i) => (
              <li key={`${a.at}-${i}`} className="flex min-w-0 items-center gap-2">
                <Badge variant={a.ok ? 'secondary' : 'destructive'} className="max-w-[45%] min-w-0 font-mono">
                  <span className="truncate">{a.tool}</span>
                </Badge>
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{a.args.url || ''}</span>
                <span className="shrink-0 tabular-nums text-muted-foreground">{fmtRelative(a.at, lang)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function clock(s: number) {
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

function useCountdown(until?: number) {
  const [now, setNow] = React.useState(() => Date.now() / 1000)
  React.useEffect(() => {
    if (!until) return
    const id = setInterval(() => setNow(Date.now() / 1000), 1000)
    return () => clearInterval(id)
  }, [until])
  return until ? Math.max(0, Math.round(until - now)) : 0
}
