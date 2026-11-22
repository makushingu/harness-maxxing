// "Name and look" of an agent: a small dialog opened by clicking its character (or its name) at the top of its
// profile - the name and the character editor, nothing else. Saved together (PATCH display_name + avatar).
import * as React from 'react'
import { Pencil } from 'lucide-react'
import { useT } from '@/i18n'
import { usePatchAgent } from '@/lib/queries'
import type { Agent, AgentAvatar, AgentDetail } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, FormField, Input, Sensitive, toast } from '@/components/ui'
import { AgentAvatarIcon } from './Avatar'
import { AvatarEditor } from './AvatarEditor'

export function AppearanceDialog({ agent: a, open, onOpenChange }: { agent: Agent; open: boolean; onOpenChange: (o: boolean) => void }) {
  const t = useT()
  const patch = usePatchAgent()
  const [name, setName] = React.useState(a.display_name)
  const [avatar, setAvatar] = React.useState<AgentAvatar>(a.avatar)
  React.useEffect(() => {
    if (open) (setName(a.display_name), setAvatar({ ...a.avatar }))
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps
  const save = () =>
    patch.mutate({ path: a.path, display_name: name.trim() || a.name, avatar }, { onSuccess: () => (toast.success(t('agents.look.saved')), onOpenChange(false)) })
  return (
    <FormDialog open={open} onOpenChange={onOpenChange} title={t('agents.look.title')} description={t('agents.look.desc')} className="md:max-w-2xl"
      formClassName="gap-5" testid="agent-appearance" saving={patch.isPending} onSave={save}>
      <FormField label={t('agents.create.name')} hint={t('agents.settings.folder', { name: a.name })}>
        <Input value={name} maxLength={60} onChange={(e) => setName(e.target.value)} data-testid="agent-appearance-name" />
      </FormField>
      <AvatarEditor value={avatar} onChange={setAvatar} project={a.project} />
    </FormDialog>
  )
}

/** A small dialog: a form, then Cancel and Save (`<testid>-save`). Also the role's (AgentMenu.tsx). */
export function FormDialog(p: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description: string; className: string; formClassName: string
  testid: string; saving: boolean; onSave: () => void; children: React.ReactNode
}) {
  const t = useT()
  return (
    <Dialog open={p.open} onOpenChange={p.onOpenChange}>
      <DialogContent className={p.className} data-testid={p.testid}>
        <DialogHeader>
          <DialogTitle>{p.title}</DialogTitle>
          <DialogDescription>{p.description}</DialogDescription>
        </DialogHeader>
        <form className={cn('grid', p.formClassName)} onSubmit={(e) => (e.preventDefault(), p.onSave())}>
          {p.children}
          <DialogFooter>
            <Button type="button" variant="ghost" onClick={() => p.onOpenChange(false)}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" loading={p.saving} data-testid={`${p.testid}-save`}>
              {t('common.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

/** The top of the profile: the character and the name as one button (a pencil on hover says it can be changed). */
export function ProfileHead({ agent: a, className }: { agent: AgentDetail; className?: string }) {
  const t = useT()
  const [open, setOpen] = React.useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={t('agents.look.edit', { name: a.display_name })}
        className={cn('group/head -m-1.5 flex min-w-0 items-center gap-3 rounded-xl p-1.5 text-left transition-colors hover:bg-muted focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none', className)}
        data-testid="agent-appearance-open"
      >
        <span className="relative shrink-0">
          <AgentAvatarIcon avatar={a.avatar} size={64} animate={a.enabled} mood={a.enabled ? 'idle' : 'sleep'} />
          <span className="absolute -right-1 -bottom-1 grid size-6 place-items-center rounded-full border bg-popover text-muted-foreground shadow-xs transition-opacity group-hover/head:opacity-100 group-focus-visible/head:opacity-100 md:opacity-0">
            <Pencil className="size-3" />
          </span>
        </span>
        <span className="grid min-w-0 flex-1">
          <span className="truncate font-semibold">
            <Sensitive length={8}>{a.display_name}</Sensitive>
          </span>
          <span className="truncate text-xs text-muted-foreground">
            <Sensitive length={10}>{`${a.project} / ${a.topic}`}</Sensitive>
          </span>
        </span>
      </button>
      <AppearanceDialog agent={a} open={open} onOpenChange={setOpen} />
    </>
  )
}
