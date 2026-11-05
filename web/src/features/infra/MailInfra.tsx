// Infra -> E-mail (tab `mail` of the Infra page, GET /api/infra/mail): view only. Grouped by domain then address:
// the chain of each address (contact@site -> Cloudflare / Hostinger -> a mailbox, ending in the E-mail page or not),
// the mailboxes of the E-mail page with their last check, and the DNS health of every mail domain with what to fix.
// Nothing is created or changed at a provider from here.
import * as React from 'react'
import { Link } from 'react-router'
import { AlertTriangle, ArrowRight, Check, Inbox, KeyRound, Mail, Plus, RefreshCw, Settings2 } from 'lucide-react'
import { useInfraMail, type InfraMailView, type MailDomainHealth, type MailProblem, type MailRoute } from '@/lib/queries/infraMail'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { cn } from '@/lib/utils'
import { tDyn, useLang, useT, type TFn, type TKey, type TVars } from '@/i18n'
import { Badge, Button, EmptyState, Sensitive, Skeleton, StatusDot, toast, type DotTone } from '@/components/ui'

const LEVEL_TONE: Record<MailProblem['level'], DotTone> = { error: 'error', warn: 'warn', info: 'info' }
const LEVEL_RANK: Record<MailProblem['level'], number> = { error: 0, warn: 1, info: 2 }

/** A translated text with variables, or the server's English text while the key is missing. */
function tr(t: TFn, key: string, vars: TVars, fallback: string): string {
  const s = t(key as TKey, vars)
  return !s || s === key ? fallback : s
}

function Callout({ tone, children }: { tone: 'warn' | 'error'; children: React.ReactNode }) {
  return (
    <div className={cn('flex gap-2 rounded-lg border p-2.5 text-[13px]', tone === 'warn' ? 'border-warning/40 bg-warning/5' : 'border-destructive/40 bg-destructive/5')}>
      <AlertTriangle className={cn('mt-0.5 size-4 shrink-0', tone === 'warn' ? 'text-warning' : 'text-destructive')} />
      <div className="grid min-w-0 gap-1">{children}</div>
    </div>
  )
}

function Sources({ v }: { v: InfraMailView }) {
  const t = useT()
  const cf = v.cloudflare
  const hs = v.hostinger
  const pill = (key: string, tone: DotTone, label: string, extra?: React.ReactNode) => (
    <span key={key} className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs">
      <StatusDot tone={tone} /> {label}
      {extra && <span className="text-muted-foreground">{extra}</span>}
    </span>
  )
  const connect = (key: string, name: string) => (
    <Link key={key} to="/settings/keys" className="inline-flex items-center gap-1.5 rounded-full border border-dashed px-2.5 py-0.5 text-xs text-muted-foreground hover:bg-accent pointer-coarse:min-h-10">
      <KeyRound className="size-3" /> {t('infra.connect', { name })}
    </Link>
  )
  const on = cf.zones.filter((z) => z.routing?.enabled).length
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="infra-mail-sources">
      {pill('page', v.mail_page ? 'ok' : 'idle', t('infra.mail.page'), t('infra.mail.nBoxes', { count: v.mailboxes.length }))}
      {!cf.connected
        ? connect('cf', 'Cloudflare')
        : cf.error
          ? pill('cf', 'error', 'Cloudflare', tDyn(t, `infra.why.${cf.error}`, cf.message || cf.error))
          : pill('cf', cf.missing_permission_zones ? 'warn' : 'ok', 'Cloudflare Email Routing', t('infra.mail.zonesOn', { on, count: cf.zones.length }))}
      {!hs.connected
        ? connect('hs', 'Hostinger')
        : hs.error
          ? pill('hs', 'error', 'Hostinger', tDyn(t, `infra.why.${hs.error}`, hs.message || hs.error))
          : pill('hs', hs.orders.length ? 'ok' : 'idle', 'Hostinger Email', hs.orders.length ? t('infra.mail.nPlans', { count: hs.orders.length }) : t('infra.mail.noHostingerPlan'))}
      <span className="text-xs text-muted-foreground">{t('infra.mail.others')}</span>
    </div>
  )
}

function AddressLink({ address, account }: { address: string; account: string | null }) {
  const t = useT()
  if (account)
    return (
      <Link to={`/mail?account=${encodeURIComponent(account)}`} className="inline-flex items-center gap-1 text-success hover:underline">
        <Check className="size-3.5" /> {t('infra.mail.inPage')}
      </Link>
    )
  return (
    <Button variant="outline" size="sm" className="h-6 px-2 text-[11px]" asChild>
      <Link to={`/mail?add=${encodeURIComponent(address)}`}>
        <Plus /> {t('infra.mail.addToPage')}
      </Link>
    </Button>
  )
}

function RouteLine({ r }: { r: MailRoute }) {
  const t = useT()
  const via = r.via === 'cloudflare' ? 'Cloudflare' : 'Hostinger'
  return (
    <li className={cn('flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-[13px]', !r.enabled && 'opacity-60')} data-testid="infra-mail-route">
      <span className="font-medium break-all">
        <Sensitive>{r.address.startsWith('*@') ? t('infra.mail.catchAll', { domain: r.domain }) : r.address}</Sensitive>
      </span>
      <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
      <Badge variant="muted">
        {via} · {tDyn(t, `infra.mail.kind.${r.kind}`, r.kind)}
      </Badge>
      {r.kind === 'mailbox' && <AddressLink address={r.address} account={r.account} />}
      {r.kind === 'worker' && r.worker && (
        <span className="font-mono text-xs">
          <Sensitive>{r.worker}</Sensitive>
        </span>
      )}
      {r.kind === 'drop' && <span className="text-xs text-muted-foreground">{t('infra.mail.dropped')}</span>}
      {r.to.map((d) => (
        <span key={d.address} className="inline-flex flex-wrap items-center gap-1.5">
          <ArrowRight className="size-3.5 shrink-0 text-muted-foreground" />
          <span className="break-all">
            <Sensitive>{d.address}</Sensitive>
          </span>
          {d.verified === false && <Badge variant="warning">{t('infra.mail.notVerified')}</Badge>}
          <AddressLink address={d.address} account={d.account} />
        </span>
      ))}
      {!r.enabled && <Badge variant="muted">{t('infra.mail.off')}</Badge>}
    </li>
  )
}

function Problem({ p }: { p: MailProblem }) {
  const t = useT()
  return (
    <li className="flex gap-2 text-[13px]">
      <StatusDot tone={LEVEL_TONE[p.level]} className="mt-1.5" label={t(`infra.mail.level.${p.level}`)} />
      <div className="grid min-w-0 gap-0.5">
        <span>
          <Sensitive>{tr(t, `infra.mail.p.${p.code}`, p.params, p.text)}</Sensitive>
        </span>
        {p.fix && (
          <span className="text-xs break-words text-muted-foreground">
            <Sensitive>{tr(t, `infra.mail.f.${p.code}`, p.params, p.fix)}</Sensitive>
          </span>
        )}
      </div>
    </li>
  )
}

function Health({ h }: { h: MailDomainHealth }) {
  const t = useT()
  const lang = useLang()
  const shown = h.problems.filter((p) => p.code !== 'no_mail').sort((a, b) => LEVEL_RANK[a.level] - LEVEL_RANK[b.level])
  const chip = (label: string, good: boolean | null, value: string) => (
    <span className="inline-flex min-w-0 items-center gap-1.5 text-xs">
      <StatusDot tone={good === null ? 'idle' : good ? 'ok' : 'warn'} />
      <span className="font-medium">{label}</span>
      <span className="truncate text-muted-foreground">
        <Sensitive>{value}</Sensitive>
      </span>
    </span>
  )
  if (h.problems.some((p) => p.code === 'no_mail'))
    return <p className="px-3 py-2 text-xs text-muted-foreground">{t('infra.mail.noMail')}</p>
  return (
    <div className="grid gap-2 px-3 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="text-xs font-semibold text-muted-foreground">{t('infra.mail.dns')}</span>
        {chip('MX', h.mx.length > 0 && h.mx[0] !== '', h.mx.length ? h.mx.join(', ') : t('infra.mail.none'))}
        {chip('SPF', h.spf.count === 1, h.spf.count === 1 ? h.spf.record || '' : h.spf.count ? t('infra.mail.nRecords', { count: h.spf.count }) : t('infra.mail.none'))}
        {chip('DKIM', h.dkim.length ? true : null, h.dkim.length ? h.dkim.join(', ') : t('infra.mail.notFound'))}
        {chip('DMARC', h.dmarc.count === 1 && !!h.dmarc.policy, h.dmarc.policy ? `p=${h.dmarc.policy}` : h.dmarc.count ? t('infra.mail.nRecords', { count: h.dmarc.count }) : t('infra.mail.none'))}
        {h.checked && <span className="ml-auto text-[11px] text-muted-foreground">{t('infra.mail.checked', { when: fmtRelative(h.checked, lang) })}</span>}
      </div>
      {shown.length > 0 ? (
        <ul className="grid gap-1.5">
          {shown.map((p) => (
            <Problem key={p.code} p={p} />
          ))}
        </ul>
      ) : (
        <p className="text-xs text-success">{t('infra.mail.dnsOk')}</p>
      )}
    </div>
  )
}

function DomainCard({ domain, v }: { domain: string; v: InfraMailView }) {
  const t = useT()
  const lang = useLang()
  const zone = v.cloudflare.zones.find((z) => z.name === domain)
  const order = v.hostinger.orders.find((o) => o.domain === domain)
  const routes = v.routes.filter((r) => r.domain === domain)
  const boxes = v.mailboxes.filter((b) => b.domain === domain)
  const health = v.domains.find((d) => d.domain === domain)
  const bad = (health?.problems || []).filter((p) => p.level === 'error').length
  const warn = (health?.problems || []).filter((p) => p.level === 'warn').length
  return (
    <section className="grid grid-cols-[minmax(0,1fr)] overflow-hidden rounded-xl border bg-card" data-testid="infra-mail-domain">
      <header className="flex flex-wrap items-center gap-2 border-b px-3 py-2">
        <Mail className="size-4 shrink-0 text-primary" />
        <h3 className="truncate text-sm font-semibold">
          <Sensitive>{domain}</Sensitive>
        </h3>
        {zone?.routing && (
          <Badge variant={zone.routing.enabled ? 'success' : 'muted'}>
            Cloudflare · {zone.routing.enabled ? t('infra.mail.routingOn') : t('infra.mail.routingOff')}
          </Badge>
        )}
        {zone?.missing_permission && <Badge variant="warning">Cloudflare · {t('infra.mail.noPermission')}</Badge>}
        {zone?.error && !zone.missing_permission && <Badge variant="destructive">Cloudflare · {tDyn(t, `infra.why.${zone.error}`, zone.message || zone.error)}</Badge>}
        {order && (
          <Badge variant="muted">
            Hostinger · <Sensitive>{order.plan || order.status || ''}</Sensitive>
          </Badge>
        )}
        {health && (
          <span className={cn('ml-auto text-xs', bad ? 'text-destructive' : warn ? 'text-warning' : 'text-muted-foreground')}>
            {bad ? t('infra.mail.nErrors', { count: bad }) : warn ? t('infra.mail.nWarnings', { count: warn }) : health.problems.some((p) => p.code === 'no_mail') ? '' : t('infra.mail.dnsOk')}
          </span>
        )}
      </header>
      {zone?.routing?.status && zone.routing.enabled && zone.routing.status !== 'ready' && (
        <p className="border-b px-3 py-1.5 text-xs text-warning">{t('infra.mail.routingStatus', { status: zone.routing.status })}</p>
      )}
      {zone?.missing_permission && (
        <p className="border-b px-3 py-1.5 text-xs text-muted-foreground">{t('infra.mail.rulesHidden')}</p>
      )}
      {(routes.length > 0 || boxes.length > 0) && (
        <ul className="divide-y border-b">
          {routes.map((r, i) => (
            <RouteLine key={`${r.via}-${r.kind}-${r.address}-${i}`} r={r} />
          ))}
          {boxes.map((b) => (
            <li key={b.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-2 text-[13px]" data-testid="infra-mail-box">
              <Inbox className="size-3.5 shrink-0 text-primary" />
              <Link to={`/mail?account=${encodeURIComponent(b.id)}`} className="font-medium break-all hover:underline">
                <Sensitive>{b.address}</Sensitive>
              </Link>
              <Badge variant="muted">{t('infra.mail.page')}</Badge>
              <span className="text-xs text-muted-foreground">
                IMAP <Sensitive>{`${b.imap_host || ''}:${b.imap_port || ''}`}</Sensitive> · SMTP <Sensitive>{`${b.smtp_host || ''}:${b.smtp_port || ''}`}</Sensitive>
              </span>
              <span className="ml-auto inline-flex items-center gap-1.5 text-xs">
                {!b.last_check ? (
                  <span className="text-muted-foreground">{t('infra.mail.notChecked')}</span>
                ) : b.last_check.ok ? (
                  <>
                    <StatusDot tone="ok" /> {t('infra.mail.checkOk', { when: fmtRelative(b.last_check.at, lang) })}
                  </>
                ) : (
                  <>
                    <StatusDot tone="error" />
                    <span className="text-destructive">
                      {t('infra.mail.checkFailed', { when: fmtRelative(b.last_check.at, lang) })} <Sensitive>{b.last_check.error}</Sensitive>
                    </span>
                  </>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}
      {!routes.length && !boxes.length && zone?.routing?.enabled && <p className="border-b px-3 py-2 text-xs text-muted-foreground">{t('infra.mail.noRule')}</p>}
      {health ? <Health h={health} /> : <p className="px-3 py-2 text-xs text-muted-foreground">{t('infra.mail.publicDomain')}</p>}
    </section>
  )
}

export function MailInfra() {
  const t = useT()
  const lang = useLang()
  const { data: v, isLoading, error, refresh, refreshing, refetch } = useInfraMail()
  const doRefresh = () => refresh().catch((e) => toast.error(errorMessage(e)))

  if (isLoading)
    return (
      <div className="grid gap-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-36 rounded-xl" />
        ))}
      </div>
    )
  if (error || !v)
    return (
      <EmptyState
        tone="error"
        icon={AlertTriangle}
        title={t('infra.mail.loadError')}
        description={error ? errorMessage(error) : ''}
        action={<Button onClick={() => void refetch()}>{t('infra.mail.retry')}</Button>}
        compact
      />
    )

  const cf = v.cloudflare
  const offZones = cf.zones.filter((z) => z.routing && !z.routing.enabled).map((z) => z.name)
  const domains = [...new Set([...v.domains.map((d) => d.domain), ...v.routes.map((r) => r.domain), ...v.mailboxes.map((b) => b.domain)])].filter(Boolean)
  const used = (d: string) => v.routes.some((r) => r.domain === d) || v.mailboxes.some((b) => b.domain === d)
  // zones whose rules are unreadable and that have no MX: no card, one line at the end
  const quiet = domains.filter((d) => !used(d) && v.domains.find((x) => x.domain === d)?.problems.some((p) => p.code === 'no_mail'))
  const cards = domains.filter((d) => !quiet.includes(d)).sort((a, b) => Number(used(b)) - Number(used(a)) || a.localeCompare(b))

  return (
    <div className={cn('grid grid-cols-[minmax(0,1fr)] gap-4', refreshing && 'opacity-60')} data-testid="infra-mail">
      <div className="flex flex-wrap items-center gap-2">
        <Sources v={v} />
        <span className="ml-auto flex items-center gap-2 text-xs text-muted-foreground">
          {v.generated_at && t('infra.updated', { when: fmtRelative(v.generated_at, lang) })}
          <Button variant="outline" size="sm" loading={refreshing} onClick={doRefresh} data-testid="infra-mail-refresh">
            <RefreshCw /> {t('infra.refresh')}
          </Button>
        </span>
      </div>
      <p className="text-[13px] text-muted-foreground">{t('infra.mail.hint')}</p>
      {!v.mail_page && (
        <Callout tone="warn">
          <span>{t('infra.mail.pageOff')}</span>
          <Link to="/settings/features" className="inline-flex items-center gap-1 text-primary hover:underline">
            <Settings2 className="size-3.5" /> {t('infra.turnOn')}
          </Link>
        </Callout>
      )}
      {!!cf.missing_permission_zones && (
        <Callout tone="warn">
          <span className="font-medium">{t('infra.mail.permTitle', { count: cf.missing_permission_zones })}</span>
          <span>{t('infra.mail.permFix')}</span>
          <Link to="/settings/keys" className="inline-flex items-center gap-1 text-primary hover:underline">
            <KeyRound className="size-3.5" /> {t('infra.mail.openKeys')}
          </Link>
        </Callout>
      )}
      {cf.addresses_fix && (
        <Callout tone="warn">
          <span>{t('infra.mail.addrFix')}</span>
        </Callout>
      )}
      {cards.length ? (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 xl:grid-cols-2">
          {cards.map((d) => (
            <DomainCard key={d} domain={d} v={v} />
          ))}
        </div>
      ) : (
        <EmptyState icon={Mail} title={t('infra.mail.empty')} description={t('infra.mail.emptyHint')} compact />
      )}
      {quiet.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('infra.mail.quietZones', { count: quiet.length })} <Sensitive>{quiet.join(', ')}</Sensitive>
        </p>
      )}
      {offZones.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {t('infra.mail.offZones', { count: offZones.length })} <Sensitive>{offZones.join(', ')}</Sensitive>
        </p>
      )}
    </div>
  )
}
