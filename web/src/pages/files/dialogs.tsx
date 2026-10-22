// Dialogs of the Files page: name/path prompt (new file, new folder, rename/move) and save conflict.
import * as React from 'react'
import { AlertTriangle } from 'lucide-react'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input } from '@/components/ui'
import { useT } from '@/i18n'

export type NameDialogState = {
  title: string
  description?: React.ReactNode
  label: string
  initial: string
  confirmText: string
  /** Returns an error message to show inline, or null when done (the dialog closes). */
  submit: (value: string) => Promise<string | null>
} | null

export function NameDialog({ state, onClose }: { state: NameDialogState; onClose: () => void }) {
  const t = useT()
  const [value, setValue] = React.useState('')
  const [error, setError] = React.useState<string | null>(null)
  const [busy, setBusy] = React.useState(false)
  const input = React.useRef<HTMLInputElement>(null)
  React.useEffect(() => {
    if (!state) return
    setValue(state.initial)
    setError(null)
    setBusy(false)
  }, [state])
  const open = !!state
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()}>
      <DialogContent
        onOpenAutoFocus={(e) => {
          // Select the stem ("notes" in "notes.md") like a desktop file manager.
          e.preventDefault()
          const el = input.current
          if (!el) return
          el.focus()
          const v = el.value
          const slash = v.lastIndexOf('/') + 1
          const dot = v.lastIndexOf('.')
          el.setSelectionRange(slash, dot > slash ? dot : v.length)
        }}
      >
        <form
          className="grid gap-4"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!state) return
            const v = value.trim()
            if (!v) return setError(t('files.nameRequired'))
            setBusy(true)
            const err = await state.submit(v).catch((x: Error) => x.message)
            setBusy(false)
            if (err) setError(err)
            else onClose()
          }}
        >
          <DialogHeader>
            <DialogTitle>{state?.title}</DialogTitle>
            {state?.description && <DialogDescription>{state.description}</DialogDescription>}
          </DialogHeader>
          <FormField label={state?.label} error={error}>
            <Input
              ref={input}
              value={value}
              onChange={(e) => {
                setValue(e.target.value)
                setError(null)
              }}
              autoComplete="off"
              spellCheck={false}
              autoCapitalize="off"
            />
          </FormField>
          <DialogFooter>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={busy} disabled={!value.trim()}>
              {state?.confirmText}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

export type ConflictChoice = 'reload' | 'overwrite' | 'copy'

/** 409 on save: the file changed on disk since it was opened. */
export function ConflictDialog({ open, busy, onChoose, onCancel }: { open: boolean; busy: ConflictChoice | null; onChoose: (c: ConflictChoice) => void; onCancel: () => void }) {
  const t = useT()
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onCancel()}>
      <DialogContent className="md:max-w-md">
        <DialogHeader>
          <div className="mb-1 flex size-10 items-center justify-center rounded-lg bg-warning/15 text-warning">
            <AlertTriangle className="size-5" />
          </div>
          <DialogTitle>{t('files.conflictTitle')}</DialogTitle>
          <DialogDescription>{t('files.conflictDesc')}</DialogDescription>
        </DialogHeader>
        <div className="grid gap-2">
          <ChoiceButton title={t('files.conflictCopy')} hint={t('files.conflictCopyHint')} loading={busy === 'copy'} disabled={!!busy} onClick={() => onChoose('copy')} />
          <ChoiceButton title={t('files.conflictReload')} hint={t('files.conflictReloadHint')} loading={busy === 'reload'} disabled={!!busy} onClick={() => onChoose('reload')} />
          <ChoiceButton title={t('files.conflictOverwrite')} hint={t('files.conflictOverwriteHint')} loading={busy === 'overwrite'} disabled={!!busy} onClick={() => onChoose('overwrite')} destructive />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onCancel} disabled={!!busy}>
            {t('files.keepEditing')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ChoiceButton({ title, hint, onClick, loading, disabled, destructive }: { title: string; hint: string; onClick: () => void; loading?: boolean; disabled?: boolean; destructive?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-busy={loading || undefined}
      className="grid gap-0.5 rounded-lg border px-3.5 py-2.5 text-left transition-colors outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60"
    >
      <span className={destructive ? 'text-sm font-medium text-destructive' : 'text-sm font-medium'}>{title}</span>
      <span className="text-[13px] text-muted-foreground">{hint}</span>
    </button>
  )
}
