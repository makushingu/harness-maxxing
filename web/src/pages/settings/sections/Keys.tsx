import * as React from 'react'
import { Copy, Eye, EyeOff, KeyRound, MoreHorizontal, Pencil, Plus, Trash2 } from 'lucide-react'
import { revealSecret, useDeleteSecret, usePutSecret, useSecrets } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { fmtRelative } from '@/lib/format'
import { copyText } from '@/lib/utils'
import type { Secret } from '@/lib/types'
import { useLang, useT } from '@/i18n'
import {
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
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  EmptyState,
  FormField,
  Input,
  Label,
  SecretInput,
  Sensitive,
  Skeleton,
  Switch,
  Tooltip,
  confirm,
  toast,
} from '@/components/ui'
import { Callout } from '@/features/common'
import { SettingsCard, SectionStack } from './ui'

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/

function SecretDialog({ open, onOpenChange, editing }: { open: boolean; onOpenChange: (o: boolean) => void; editing: Secret | null }) {
  const t = useT()
  const put = usePutSecret()
  const [name, setName] = React.useState('')
  const [value, setValue] = React.useState('')
  const [note, setNote] = React.useState('')
  const [expose, setExpose] = React.useState(false)
  const [errors, setErrors] = React.useState<{ name?: string; value?: string; form?: string }>({})
  React.useEffect(() => {
    if (!open) return
    setName(editing?.name || '')
    setValue('')
    setNote(editing?.note || '')
    setExpose(editing?.expose || false)
    setErrors({})
  }, [open, editing])
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: typeof errors = {}
    const n = name.trim()
    if (!NAME_RE.test(n)) errs.name = t('keys.nameInvalid')
    if (!editing && !value) errs.value = t('keys.valueRequired')
    setErrors(errs)
    if (Object.keys(errs).length) return
    put.mutate(
      { name: n, note: note.trim(), expose, ...(value ? { value } : {}) },
      {
        onSuccess: () => {
          toast.success(editing ? t('keys.updated') : t('keys.added'))
          onOpenChange(false)
        },
        onError: (err) => {
          if (isApiError(err) && ['invalid_name', 'reserved_name'].includes(err.code)) setErrors({ name: errorMessage(err) })
          else if (isApiError(err, 'value_required')) setErrors({ value: errorMessage(err) })
          else setErrors({ form: errorMessage(err) })
        },
      },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? t('keys.edit') : t('keys.add')}</DialogTitle>
          <DialogDescription>{t('keys.dialogDesc')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <FormField label={t('keys.name')} error={errors.name} hint={t('keys.nameHint')}>
            <Input value={name} onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))} disabled={!!editing} className="font-mono" placeholder="OPENAI_API_KEY" autoComplete="off" spellCheck={false} autoFocus={!editing} />
          </FormField>
          <FormField label={t('keys.value')} error={errors.value} hint={editing ? t('keys.valueKeep') : undefined}>
            <SecretInput value={value} onChange={(e) => setValue(e.target.value)} autoFocus={!!editing} placeholder={editing ? '••••••••' : ''} />
          </FormField>
          <FormField label={t('keys.note')}>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('keys.notePlaceholder')} autoComplete="off" />
          </FormField>
          <Label className="items-start justify-between gap-4 rounded-lg border p-3 leading-snug font-normal">
            <span className="grid gap-0.5">
              <span className="font-medium">{t('keys.expose')}</span>
              <span className="text-[13px] text-muted-foreground">{t('keys.exposeDesc')}</span>
            </span>
            <Switch checked={expose} onCheckedChange={setExpose} />
          </Label>
          {errors.form && <Callout tone="error">{errors.form}</Callout>}
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={put.isPending}>
              {editing ? t('common.save') : t('keys.add')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function SecretRow({ s, onEdit }: { s: Secret; onEdit: () => void }) {
  const t = useT()
  const lang = useLang()
  const put = usePutSecret()
  const del = useDeleteSecret()
  const [revealed, setRevealed] = React.useState<string | null>(null)
  const [loading, setLoading] = React.useState(false)
  // A revealed value is hidden again after 30 s and never kept in a cache.
  React.useEffect(() => {
    if (revealed === null) return
    const id = setTimeout(() => setRevealed(null), 30_000)
    return () => clearTimeout(id)
  }, [revealed])
  const reveal = async () => {
    if (revealed !== null) return setRevealed(null)
    setLoading(true)
    try {
      setRevealed((await revealSecret(s.name)).value)
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }
  const copy = async () => {
    try {
      const v = revealed ?? (await revealSecret(s.name)).value
      if (await copyText(v)) toast.success(t('keys.copied', { name: s.name }))
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1.4fr)_auto_auto]">
      <div className="grid min-w-0 gap-0.5">
        <span className="truncate font-mono text-[13px] font-medium">{s.name}</span>
        <span className="truncate text-xs text-muted-foreground">
          {s.note ? <Sensitive>{s.note}</Sensitive> : t('keys.noNote')} · {fmtRelative(s.updated, lang)}
        </span>
      </div>
      <div className="col-span-2 row-start-2 flex min-w-0 items-center gap-1 md:col-span-1 md:row-start-auto">
        <code className="min-w-0 flex-1 truncate rounded-md bg-muted/60 px-2 py-1 font-mono text-xs">
          <Sensitive length={12}>{revealed ?? s.preview}</Sensitive>
        </code>
        <Tooltip content={revealed !== null ? t('common.hide') : t('keys.reveal')}>
          <Button variant="ghost" size="icon-sm" onClick={reveal} loading={loading} aria-label={revealed !== null ? t('common.hide') : t('keys.reveal')}>
            {revealed !== null ? <EyeOff /> : <Eye />}
          </Button>
        </Tooltip>
        <Tooltip content={t('common.copy')}>
          <Button variant="ghost" size="icon-sm" onClick={copy} aria-label={t('common.copy')}>
            <Copy />
          </Button>
        </Tooltip>
      </div>
      <Tooltip content={t('keys.exposeShort')}>
        <span className="flex items-center gap-2 max-md:hidden">
          <Switch checked={s.expose} onCheckedChange={(v) => put.mutate({ name: s.name, expose: v })} aria-label={`${t('keys.expose')} ${s.name}`} />
        </span>
      </Tooltip>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('common.more')} className="col-start-2 row-start-1 md:col-start-auto md:row-start-auto">
            <MoreHorizontal />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={onEdit}>
            <Pencil /> {t('common.edit')}
          </DropdownMenuItem>
          <DropdownMenuItem className="md:hidden" onSelect={() => put.mutate({ name: s.name, expose: !s.expose })}>
            <KeyRound /> {s.expose ? t('keys.unexpose') : t('keys.exposeShort')}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            destructive
            onSelect={async () => {
              if (await confirm({ title: t('keys.deleteTitle', { name: s.name }), description: t('keys.deleteDesc'), destructive: true })) del.mutate(s.name)
            }}
          >
            <Trash2 /> {t('common.delete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )
}

export function KeysSection() {
  const t = useT()
  const { data, isLoading } = useSecrets()
  const [dialog, setDialog] = React.useState<{ open: boolean; editing: Secret | null }>({ open: false, editing: null })
  return (
    <SectionStack>
      <Callout tone="info" title={t('keys.exposeTitle')}>
        {t('keys.exposeExplain')}
      </Callout>
      <SettingsCard
        title={t('keys.vault')}
        description={t('keys.vaultDesc')}
        actions={
          <Button size="sm" onClick={() => setDialog({ open: true, editing: null })}>
            <Plus /> {t('keys.add')}
          </Button>
        }
        className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4"
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : !data?.length ? (
          <EmptyState compact icon={KeyRound} title={t('keys.empty')} description={t('keys.emptyDesc')} />
        ) : (
          <>
            <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1.4fr)_auto_auto] gap-4 border-y bg-muted/30 px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
              <span>{t('keys.name')}</span>
              <span>{t('keys.value')}</span>
              <span>{t('keys.exposeShort')}</span>
              <span className="w-8" />
            </div>
            <ul className="divide-y max-md:border-t">
              {data.map((s) => (
                <SecretRow key={s.name} s={s} onEdit={() => setDialog({ open: true, editing: s })} />
              ))}
            </ul>
          </>
        )}
      </SettingsCard>
      <SecretDialog open={dialog.open} editing={dialog.editing} onOpenChange={(o) => setDialog((d) => ({ ...d, open: o }))} />
    </SectionStack>
  )
}
