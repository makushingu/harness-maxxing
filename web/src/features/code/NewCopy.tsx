// "Separate copy" on a new session (Code mode, a topic with a git repository): the session gets its own folder and
// branch. The switch is remembered per topic, the preparation command and the .env copy per repository (server).
import * as React from 'react'
import { ChevronRight, GitBranch } from 'lucide-react'
import { Checkbox, Input, Select, Sensitive } from '@/components/ui'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { useSettings } from '@/lib/queries'
import type { CreateSessionBody } from '@/lib/types'
import { branchSlug, useCopyRepos } from './copyApi'

type Copy = NonNullable<CreateSessionBody['worktree']>
const KEY = (path: string) => `mx-copy:${path}`

/** The `worktree` field of the new session (undefined = in the topic folder, as usual). */
export function useNewCopy(path: string) {
  const { data: settings } = useSettings()
  const on = !!settings?.code_mode
  const q = useCopyRepos(path, on && !!path)
  const repos = React.useMemo(() => (q.data?.repos ?? []).filter((r) => !r.error), [q.data])
  const [want, setWant] = React.useState(() => localStorage.getItem(KEY(path)) === '1')
  React.useEffect(() => setWant(localStorage.getItem(KEY(path)) === '1'), [path])
  const [repo, setRepo] = React.useState('')
  const [base, setBase] = React.useState('')
  const [prepare, setPrepare] = React.useState<string | null>(null)
  const [env, setEnv] = React.useState<boolean | null>(null)
  const cur = repos.find((r) => r.root === repo) ?? repos[0]
  React.useEffect(() => {
    setBase('')
    setPrepare(null)
    setEnv(null)
  }, [cur?.root])
  const toggle = (v: boolean) => {
    setWant(v)
    if (v) localStorage.setItem(KEY(path), '1')
    else localStorage.removeItem(KEY(path))
  }
  const value: Copy | undefined =
    on && want && cur
      ? {
          repo: cur.root,
          base: base || undefined,
          ...(prepare !== null ? { prepare } : {}),
          ...(env !== null ? { copy_env: env } : {}),
          remember: prepare !== null || env !== null,
        }
      : undefined
  return { available: on && repos.length > 0, want, toggle, repos, cur, repo, setRepo, base, setBase, prepare, setPrepare, env, setEnv, value }
}

export function NewCopy({ c, title, id }: { c: ReturnType<typeof useNewCopy>; title: string; id: string }) {
  const t = useT()
  const [more, setMore] = React.useState(false)
  if (!c.available || !c.cur) return null
  const r = c.cur
  const bases = Array.from(new Set([...(r.default_base ? [r.default_base] : []), ...(r.branch ? [r.branch] : []), ...r.branches]))
  const prefix = r.prefs.prefix ? `${r.prefs.prefix}/` : ''
  const name = `${prefix}${branchSlug(title) || t('copy.branchFromTitle')}`
  return (
    <div className={cn('rounded-lg border has-[[data-copy-on]:checked]:border-primary/50 has-[[data-copy-on]:checked]:bg-primary/[0.06]')}>
      <label htmlFor={id} className="flex cursor-pointer items-start gap-2.5 px-3 py-2.5">
        <Checkbox id={id} data-copy-on="" checked={c.want} onCheckedChange={(v) => c.toggle(v === true)} className="mt-0.5" data-testid="new-copy" />
        <span className="grid gap-0.5 leading-tight">
          <span className="flex items-center gap-1.5 text-sm font-medium">
            <GitBranch className="size-3.5 text-primary" /> {t('copy.newLabel')}
          </span>
          <span className="text-xs text-muted-foreground">{t('copy.newHint')}</span>
        </span>
      </label>
      {c.want && (
        <div className="grid gap-2 border-t px-3 py-2.5 text-[13px]">
          {c.repos.length > 1 && (
            <Row label={t('copy.repo')}>
              <Select value={r.root} onValueChange={c.setRepo} options={c.repos.map((x) => ({ value: x.root, label: x.name }))} aria-label={t('copy.repo')} className="h-8 w-auto" />
            </Row>
          )}
          <Row label={t('copy.from')}>
            <Select value={c.base || bases[0] || ''} onValueChange={c.setBase} options={bases.map((b) => ({ value: b, label: b }))} aria-label={t('copy.from')} className="h-8 w-auto max-w-56 font-mono text-[12px]" />
          </Row>
          <Row label={t('copy.branch')}>
            <span className="truncate font-mono text-[12px] text-muted-foreground"><Sensitive>{name}</Sensitive></span>
          </Row>
          <button type="button" onClick={() => setMore((m) => !m)} className="flex w-fit items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
            <ChevronRight className={cn('size-3 transition-transform', more && 'rotate-90')} />
            {t('copy.prepareTitle')}
            {!more && (c.prepare ?? r.prefs.prepare) && <span className="font-mono">· {c.prepare ?? r.prefs.prepare}</span>}
          </button>
          {more && (
            <div className="grid gap-2 pl-4">
              <Input value={c.prepare ?? r.prefs.prepare} onChange={(e) => c.setPrepare(e.target.value)} placeholder={t('copy.preparePh')} className="h-8 font-mono text-[12px]" aria-label={t('copy.prepareTitle')} />
              <p className="text-[11px] text-muted-foreground">{t('copy.prepareHint')}</p>
              <label className="flex items-center gap-2 text-xs">
                <Checkbox checked={c.env ?? r.prefs.copy_env} onCheckedChange={(v) => c.setEnv(v === true)} />
                {t('copy.copyEnv')}
              </label>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="w-20 shrink-0 text-xs text-muted-foreground">{label}</span>
      <div className="flex min-w-0 flex-1 items-center">{children}</div>
    </div>
  )
}
