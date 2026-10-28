import * as React from 'react'
import { Link } from 'react-router'
import { KeyRound, LogIn, MoreHorizontal, Plug, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { useMcp, useMcpAdd, useMcpCheck, useMcpRemove, useSecrets, useTopics } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import type { McpServer, McpState } from '@/lib/types'
import { useLang, useT, type TKey } from '@/i18n'
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  FormField,
  Input,
  Segmented,
  Skeleton,
  Tooltip,
  confirm,
  toast,
} from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { Callout } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'
import { PcBrowserCard } from '@/features/pc/PcBrowserCard'
import { ConnectDialog } from '@/features/mcp/ConnectDialog'

const NAME_RE = /^[A-Za-z0-9_.-]{1,64}$/
// Same rule as the server (mcp._has_literal): a long token mixing letters and digits, outside ${KEY} references.
const looksSecret = (v: string) => {
  const rest = v.replace(/\$\{[A-Za-z_][A-Za-z0-9_]*(:-[^}]*)?\}/g, '')
  return (rest.match(/[A-Za-z0-9_-]{20,}/g) || []).some((x) => /[A-Za-z]/.test(x) && /[0-9]/.test(x))
}

const STATE: Record<McpState, { label: TKey; variant: 'success' | 'warning' | 'destructive' | 'muted' }> = {
  connected: { label: 'mcp.state.connected', variant: 'success' },
  needs_auth: { label: 'mcp.state.needs_auth', variant: 'warning' },
  failed: { label: 'mcp.state.failed', variant: 'destructive' },
  pending: { label: 'mcp.state.pending', variant: 'muted' },
  unknown: { label: 'mcp.state.unknown', variant: 'muted' },
}

function Where({ s }: { s: McpServer }) {
  const t = useT()
  if (!s.where.path) return <span className="text-muted-foreground">{t('mcp.everywhere')}</span>
  if (!s.where.rel) return <span className="truncate font-mono text-xs text-muted-foreground" title={s.where.path}>{s.where.path}</span>
  const label = s.where.topic ? `${s.where.project} / ${s.where.topic}` : `${s.where.project}`
  if (!s.where.exists) return <span className="truncate text-muted-foreground line-through">{label}</span>
  return (
    <Link to={`/sessions?path=${encodeURIComponent(s.where.rel)}`} className="truncate font-medium text-primary underline-offset-4 hover:underline pointer-coarse:leading-10">
      {label}
    </Link>
  )
}

type Pair = { k: string; v: string }

function Pairs({ pairs, onChange, keyLabel, keyPlaceholder, valuePlaceholder }: { pairs: Pair[]; onChange: (p: Pair[]) => void; keyLabel: string; keyPlaceholder: string; valuePlaceholder: string }) {
  const t = useT()
  const { data: secrets } = useSecrets()
  const set = (i: number, p: Partial<Pair>) => onChange(pairs.map((x, j) => (j === i ? { ...x, ...p } : x)))
  return (
    <div className="grid gap-2">
      <span className="text-sm font-medium">{keyLabel}</span>
      {pairs.map((p, i) => (
        <div key={i} className="grid gap-1">
          <div className="flex flex-wrap items-center gap-1.5 min-[400px]:flex-nowrap">
            <Input value={p.k} onChange={(e) => set(i, { k: e.target.value })} placeholder={keyPlaceholder} className="w-full font-mono text-xs min-[400px]:w-2/5" autoComplete="off" spellCheck={false} />
            <Input value={p.v} onChange={(e) => set(i, { v: e.target.value })} placeholder={valuePlaceholder} className="min-w-0 flex-1 font-mono text-xs" autoComplete="off" spellCheck={false} />
            <DropdownMenu>
              <Tooltip content={t('mcp.insertKey')}>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-sm" aria-label={t('mcp.insertKey')}>
                    <KeyRound />
                  </Button>
                </DropdownMenuTrigger>
              </Tooltip>
              <DropdownMenuContent align="end" className="max-h-72 overflow-y-auto">
                <DropdownMenuLabel>{t('mcp.insertKey')}</DropdownMenuLabel>
                {!secrets?.length && <DropdownMenuItem disabled>{t('mcp.noKeys')}</DropdownMenuItem>}
                {secrets?.map((s) => (
                  <DropdownMenuItem key={s.name} className="font-mono text-xs" onSelect={() => set(i, { v: `${p.v}\${${s.name}}` })}>
                    {s.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.delete')} onClick={() => onChange(pairs.filter((_, j) => j !== i))}>
              <X />
            </Button>
          </div>
          {looksSecret(p.v) && <span className="text-xs text-warning">{t('mcp.literalWarn')}</span>}
        </div>
      ))}
      <Button variant="ghost" size="sm" className="w-fit" onClick={() => onChange([...pairs, { k: '', v: '' }])}>
        <Plus /> {t('mcp.addLine')}
      </Button>
    </div>
  )
}

function AddDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const add = useMcpAdd()
  const { topics } = useTopics()
  const [name, setName] = React.useState('')
  const [where, setWhere] = React.useState('')
  const [kind, setKind] = React.useState<'http' | 'stdio'>('http')
  const [url, setUrl] = React.useState('')
  const [command, setCommand] = React.useState('')
  const [pairs, setPairs] = React.useState<Pair[]>([])
  const [errors, setErrors] = React.useState<{ name?: string; target?: string; form?: string }>({})
  React.useEffect(() => {
    if (!open) return
    setName('')
    setWhere('')
    setKind('http')
    setUrl('')
    setCommand('')
    setPairs([])
    setErrors({})
  }, [open])
  const options = React.useMemo(
    () => [{ value: '', label: t('mcp.everywhere') }, ...topics.map((tp) => ({ value: tp.path, label: `${tp.project} / ${tp.name}` }))],
    [topics, t],
  )
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: typeof errors = {}
    if (!NAME_RE.test(name.trim())) errs.name = t('mcp.nameInvalid')
    if (kind === 'http' && !/^https?:\/\/\S+$/.test(url.trim())) errs.target = t('mcp.urlInvalid')
    if (kind === 'stdio' && !command.trim()) errs.target = t('mcp.commandRequired')
    setErrors(errs)
    if (Object.keys(errs).length) return
    const map = Object.fromEntries(pairs.filter((p) => p.k.trim()).map((p) => [p.k.trim(), p.v]))
    add.mutate(
      kind === 'http' ? { name: name.trim(), where, type: 'http', url: url.trim(), headers: map } : { name: name.trim(), where, type: 'stdio', command: command.trim(), env: map },
      {
        onSuccess: (r) => {
          toast.success(r.exposed.length ? t('mcp.addedExposed', { name: name.trim(), keys: r.exposed.join(', ') }) : t('mcp.added', { name: name.trim() }))
          onOpenChange(false)
        },
        onError: (err) => setErrors({ form: errorMessage(err) }),
      },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('mcp.add')}</DialogTitle>
          <DialogDescription>{t('mcp.addDesc')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <FormField label={t('mcp.name')} error={errors.name}>
            <Input value={name} onChange={(e) => setName(e.target.value.replace(/[^A-Za-z0-9_.-]/g, '-'))} placeholder="google-ads" className="font-mono" autoComplete="off" spellCheck={false} autoFocus />
          </FormField>
          <FormField label={t('mcp.where')} hint={t('mcp.whereHint')}>
            <Combobox value={where} onChange={setWhere} options={options} labelOf={(v) => options.find((o) => o.value === v)?.label || v} searchPlaceholder={t('mcp.searchTopic')} />
          </FormField>
          <Segmented
            value={kind}
            onChange={setKind}
            aria-label={t('mcp.type')}
            options={[
              { value: 'http', label: t('mcp.typeHttp') },
              { value: 'stdio', label: t('mcp.typeStdio') },
            ]}
          />
          {kind === 'http' ? (
            <FormField label={t('mcp.url')} error={errors.target}>
              <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://mcp.example.com/mcp" className="font-mono text-xs" autoComplete="off" spellCheck={false} />
            </FormField>
          ) : (
            <FormField label={t('mcp.command')} error={errors.target}>
              <Input value={command} onChange={(e) => setCommand(e.target.value)} placeholder="npx -y @acme/mcp-server" className="font-mono text-xs" autoComplete="off" spellCheck={false} />
            </FormField>
          )}
          <Pairs
            pairs={pairs}
            onChange={setPairs}
            keyLabel={kind === 'http' ? t('mcp.headers') : t('mcp.env')}
            keyPlaceholder={kind === 'http' ? 'Authorization' : 'API_KEY'}
            valuePlaceholder={kind === 'http' ? 'Bearer ${MY_TOKEN}' : '${MY_TOKEN}'}
          />
          <p className="text-xs text-muted-foreground">{t('mcp.keysHint')}</p>
          {errors.form && <Callout tone="error">{errors.form}</Callout>}
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={add.isPending}>
              {t('mcp.add')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function Row({ s, onConnect }: { s: McpServer; onConnect: () => void }) {
  const t = useT()
  const remove = useMcpRemove()
  const st = STATE[s.state] || STATE.unknown
  const target = s.url || [s.command, ...(s.args || [])].filter(Boolean).join(' ')
  const canLogin = s.type === 'http' || s.type === 'sse'
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1.5 px-4 py-3 md:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto_auto]">
      <div className="grid min-w-0 gap-0.5">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate font-mono text-[13px] font-medium">{s.name}</span>
          <Badge variant="outline" className="uppercase">{s.type}</Badge>
          {s.literal_secret && (
            <Tooltip content={t('mcp.literalWarn')}>
              <Badge variant="warning">{t('mcp.literal')}</Badge>
            </Tooltip>
          )}
        </span>
        <span className="truncate font-mono text-xs text-muted-foreground" title={target}>
          {target}
        </span>
      </div>
      <div className="col-span-2 row-start-2 flex min-w-0 text-[13px] md:col-span-1 md:row-start-auto">
        <Where s={s} />
      </div>
      <Tooltip content={s.detail || t(st.label)}>
        <Badge variant={st.variant} className="max-md:col-start-1 max-md:row-start-3">
          {t(st.label)}
        </Badge>
      </Tooltip>
      <div className="col-start-2 row-start-1 flex items-center gap-1 md:col-start-auto md:row-start-auto">
        {s.state === 'needs_auth' && (
          <Button size="sm" onClick={onConnect}>
            <LogIn /> {t('mcp.connect')}
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label={t('common.more')}>
              <MoreHorizontal />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            {canLogin && (
              <DropdownMenuItem onSelect={onConnect}>
                <LogIn /> {s.state === 'connected' ? t('mcp.reconnect') : t('mcp.connect')}
              </DropdownMenuItem>
            )}
            {canLogin && <DropdownMenuSeparator />}
            <DropdownMenuItem
              destructive
              onSelect={async () => {
                if (await confirm({ title: t('mcp.removeTitle', { name: s.name }), description: t('mcp.removeDesc'), destructive: true })) remove.mutate(s.id)
              }}
            >
              <Trash2 /> {t('mcp.remove')}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </li>
  )
}

export function McpSection() {
  const t = useT()
  const lang = useLang()
  const { data, isLoading } = useMcp()
  const check = useMcpCheck()
  const [adding, setAdding] = React.useState(false)
  const [connecting, setConnecting] = React.useState<McpServer | null>(null)
  const servers = data?.servers || []
  const checking = data?.checking || check.isPending
  return (
    <SectionStack>
      <Callout tone="info" title={t('mcp.whatTitle')}>
        {t('mcp.whatExplain')}
      </Callout>
      <SettingsCard
        title={t('mcp.servers')}
        description={data?.checked_at ? t('mcp.checkedAt', { when: fmtRelative(data.checked_at, lang) }) : t('mcp.serversDesc')}
        actions={
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" onClick={() => check.mutate()} disabled={checking || !servers.length}>
              <RefreshCw className={checking ? 'animate-spin' : undefined} /> {checking ? t('mcp.checking') : t('mcp.check')}
            </Button>
            <Button size="sm" onClick={() => setAdding(true)}>
              <Plus /> {t('mcp.add')}
            </Button>
          </div>
        }
        className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4"
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : !servers.length ? (
          <EmptyState compact icon={Plug} title={t('mcp.empty')} description={t('mcp.emptyDesc')} />
        ) : (
          <>
            <div className="hidden grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_auto_auto] gap-4 border-y bg-muted/30 px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
              <span>{t('mcp.name')}</span>
              <span>{t('mcp.where')}</span>
              <span>{t('mcp.stateCol')}</span>
              <span className="w-8" />
            </div>
            <ul className="divide-y max-md:border-t">
              {servers.map((s) => (
                <Row key={s.id} s={s} onConnect={() => setConnecting(s)} />
              ))}
            </ul>
          </>
        )}
      </SettingsCard>
      <PcBrowserCard />
      <AddDialog open={adding} onOpenChange={setAdding} />
      <ConnectDialog server={connecting} onClose={() => setConnecting(null)} />
    </SectionStack>
  )
}
