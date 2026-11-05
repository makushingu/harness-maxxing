import * as React from 'react'
import { FileKey, KeyRound, MoreHorizontal, Pencil, Plus, Trash2, Upload } from 'lucide-react'
import { useDeleteSecretFile, usePutSecretFile, useSecretFiles } from '@/lib/queries'
import { errorMessage, isApiError } from '@/lib/api'
import { fmtBytes, fmtRelative } from '@/lib/format'
import type { SecretFile } from '@/lib/types'
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
  Sensitive,
  Skeleton,
  Switch,
  Tooltip,
  confirm,
  toast,
} from '@/components/ui'
import { Callout } from '@/features/common'
import { SettingsCard } from './ui'

const NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/
/** Same cap as the server (the global body limit). */
const MAX_BYTES = 1024 * 1024

type Errors = { name?: string; file?: string; form?: string }

/** Server error code -> translated text (the server's message is English only). */
function useFileError() {
  const t = useT()
  return (err: unknown): { field: 'name' | 'file' | 'form'; text: string } => {
    if (isApiError(err)) {
      switch (err.code) {
        case 'invalid_name':
          return { field: 'name', text: t('keyfiles.err.invalidName') }
        case 'reserved_name':
          return { field: 'name', text: t('keyfiles.err.reservedName') }
        case 'name_taken':
          return { field: 'name', text: t('keyfiles.err.nameTaken') }
        case 'exists':
          return { field: 'name', text: t('keyfiles.err.exists') }
        case 'file_required':
          return { field: 'file', text: t('keyfiles.err.fileRequired') }
        case 'too_large':
        case 'invalid_value':
          return { field: 'file', text: t('keyfiles.err.tooLarge') }
      }
    }
    return { field: 'form', text: errorMessage(err) }
  }
}

function FileDialog({ open, onOpenChange, editing }: { open: boolean; onOpenChange: (o: boolean) => void; editing: SecretFile | null }) {
  const t = useT()
  const put = usePutSecretFile()
  const describe = useFileError()
  const { data: existing } = useSecretFiles()
  const [name, setName] = React.useState('')
  const [file, setFile] = React.useState<File | null>(null)
  const [note, setNote] = React.useState('')
  const [expose, setExpose] = React.useState(false)
  const [errors, setErrors] = React.useState<Errors>({})
  const input = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    if (!open) return
    setName(editing?.name || '')
    setFile(null)
    setNote(editing?.note || '')
    setExpose(editing?.expose || false)
    setErrors({})
  }, [open, editing])
  const pick = (f: File | null) => {
    setFile(f)
    if (f && f.size > MAX_BYTES) setErrors((e) => ({ ...e, file: t('keyfiles.err.tooLarge') }))
    else setErrors((e) => ({ ...e, file: undefined }))
  }
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const errs: Errors = {}
    const n = name.trim()
    if (!NAME_RE.test(n)) errs.name = t('keys.nameInvalid')
    else if (!editing && existing?.some((s) => s.name === n)) errs.name = t('keyfiles.err.exists')
    if (!editing && !file) errs.file = t('keyfiles.err.fileRequired')
    else if (file && file.size === 0) errs.file = t('keyfiles.err.empty')
    else if (file && file.size > MAX_BYTES) errs.file = t('keyfiles.err.tooLarge')
    setErrors(errs)
    if (Object.keys(errs).length) return
    put.mutate(
      // create: the server refuses (409) a name added meanwhile instead of replacing that file
      { name: n, note: note.trim(), expose, ...(file ? { file } : {}), ...(editing ? {} : { create: true }) },
      {
        onSuccess: () => {
          toast.success(editing ? t('keyfiles.updated') : t('keyfiles.added'))
          onOpenChange(false)
        },
        onError: (err) => {
          const { field, text } = describe(err)
          setErrors({ [field]: text })
        },
      },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{editing ? t('keyfiles.edit') : t('keyfiles.add')}</DialogTitle>
          <DialogDescription>{t('keyfiles.dialogDesc')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={submit} className="grid gap-4" noValidate>
          <FormField label={t('keys.name')} error={errors.name} hint={t('keyfiles.nameHint')}>
            <Input value={name} onChange={(e) => setName(e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_'))} disabled={!!editing} className="font-mono" placeholder="ANDROID_KEYSTORE" autoComplete="off" spellCheck={false} autoFocus={!editing} />
          </FormField>
          <FormField label={t('keyfiles.file')} error={errors.file} hint={editing ? t('keyfiles.fileKeep', { filename: editing.filename || editing.name }) : t('keyfiles.fileHint')}>
            <div className="flex min-w-0 items-center gap-2">
              <input ref={input} type="file" className="hidden" onChange={(e) => pick(e.target.files?.[0] ?? null)} aria-label={t('keyfiles.file')} />
              <Button variant="outline" onClick={() => input.current?.click()}>
                <Upload /> {t(file || editing ? 'keyfiles.replace' : 'keyfiles.choose')}
              </Button>
              <span className="min-w-0 truncate text-[13px] text-muted-foreground">{file ? `${file.name} · ${fmtBytes(file.size)}` : t('keyfiles.noneChosen')}</span>
            </div>
          </FormField>
          <FormField label={t('keys.note')}>
            <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t('keys.notePlaceholder')} autoComplete="off" maxLength={200} />
          </FormField>
          <Label className="items-start justify-between gap-4 rounded-lg border p-3 leading-snug font-normal">
            <span className="grid gap-0.5">
              <span className="font-medium">{t('keyfiles.expose')}</span>
              <span className="text-[13px] text-muted-foreground">{t('keyfiles.exposeDesc', { name: name.trim() || 'NAME' })}</span>
            </span>
            <Switch checked={expose} onCheckedChange={setExpose} />
          </Label>
          {errors.form && <Callout tone="error">{errors.form}</Callout>}
          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={put.isPending}>
              {editing ? t('common.save') : t('keyfiles.add')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function FileRow({ f, onEdit }: { f: SecretFile; onEdit: () => void }) {
  const t = useT()
  const lang = useLang()
  const put = usePutSecretFile()
  const del = useDeleteSecretFile()
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-2 px-4 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1.4fr)_auto_auto]">
      <div className="grid min-w-0 gap-0.5">
        <span className="font-mono text-[13px] font-medium [overflow-wrap:anywhere]">{f.name}</span>
        <span className="flex min-w-0 text-xs text-muted-foreground">
          <span className="truncate">{f.note ? <Sensitive>{f.note}</Sensitive> : t('keys.noNote')}</span>
          <span className="shrink-0 whitespace-pre"> · {fmtRelative(f.updated, lang)}</span>
        </span>
      </div>
      <div className="col-span-2 row-start-2 flex min-w-0 items-center gap-2 md:col-span-1 md:row-start-auto">
        <FileKey className="size-4 shrink-0 text-muted-foreground" aria-hidden />
        <span className="grid min-w-0 flex-1 gap-0.5 text-xs">
          <span className="truncate font-mono" title={f.filename}>{f.filename || '–'}</span>
          <span className="text-muted-foreground">{fmtBytes(f.size)}</span>
        </span>
        <code className="shrink-0 rounded-md bg-muted/60 px-2 py-1 font-mono text-xs" title={`SHA-256 ${f.sha256}`}>
          {f.sha256.slice(0, 12)}
        </code>
      </div>
      <Tooltip content={t('keyfiles.exposeTip', { name: f.name })}>
        <span className="flex items-center gap-2 max-md:hidden">
          <Switch checked={f.expose} onCheckedChange={(v) => put.mutate({ name: f.name, expose: v })} aria-label={`${t('keyfiles.expose')} ${f.name}`} />
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
          <DropdownMenuItem className="md:hidden" onSelect={() => put.mutate({ name: f.name, expose: !f.expose })}>
            <KeyRound /> {f.expose ? t('keys.unexpose') : t('keys.exposeShort')}
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem
            destructive
            onSelect={async () => {
              if (await confirm({ title: t('keyfiles.deleteTitle', { name: f.name }), description: t('keyfiles.deleteDesc'), destructive: true })) del.mutate(f.name)
            }}
          >
            <Trash2 /> {t('common.delete')}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </li>
  )
}

/** "Files" part of Settings -> Keys: secret files (keystore, service-account JSON, certificate). The content is
 *  never shown nor downloadable; only the description is listed. */
export function KeyFilesCard() {
  const t = useT()
  const { data, isLoading } = useSecretFiles()
  const [dialog, setDialog] = React.useState<{ open: boolean; editing: SecretFile | null }>({ open: false, editing: null })
  return (
    <>
      <SettingsCard
        title={t('keyfiles.title')}
        description={t('keyfiles.desc')}
        actions={
          <Button size="sm" onClick={() => setDialog({ open: true, editing: null })}>
            <Plus /> {t('keyfiles.add')}
          </Button>
        }
        className="[&>div:last-child]:p-0 [&>div:last-child]:pt-4"
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            {[0, 1].map((i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : !data?.length ? (
          <EmptyState compact icon={FileKey} title={t('keyfiles.empty')} description={t('keyfiles.emptyDesc')} />
        ) : (
          <>
            <div className="hidden grid-cols-[minmax(0,1.2fr)_minmax(0,1.4fr)_auto_auto] gap-4 border-y bg-muted/30 px-4 py-2 text-xs font-medium text-muted-foreground md:grid">
              <span>{t('keys.name')}</span>
              <span>{t('keyfiles.file')}</span>
              <span>{t('keys.exposeShort')}</span>
              <span className="w-8" />
            </div>
            <ul className="divide-y max-md:border-t">
              {data.map((f) => (
                <FileRow key={f.name} f={f} onEdit={() => setDialog({ open: true, editing: f })} />
              ))}
            </ul>
          </>
        )}
        <p className="border-t px-4 py-3 text-xs text-muted-foreground">{t('keyfiles.safety')}</p>
      </SettingsCard>
      <FileDialog open={dialog.open} editing={dialog.editing} onOpenChange={(o) => setDialog((d) => ({ ...d, open: o }))} />
    </>
  )
}
