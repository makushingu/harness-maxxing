// Team dialogs: send a message to a session, create a poll, start a chat.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Check, MessageSquarePlus, MessagesSquare, Plus, Trash2, UserPlus, Users } from 'lucide-react'
import { useSessions, useTeamCreateChat, useTeamForward, useTeamPoll, useTopics, type TeamMessage, type TeamState } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label, Segmented, Textarea, toast } from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { Avatar } from '@/features/profile/Avatar'

/* ------------------------------------------------------------------------------------------------ to a session */
export function ForwardDialog({
  open, onOpenChange, chatId, message, initialText, suggestedTitle,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  chatId: string
  message: TeamMessage | null
  initialText: string
  suggestedTitle: string
}) {
  const t = useT()
  const navigate = useNavigate()
  const { data: sessions } = useSessions(undefined, false, open)
  const { topics } = useTopics()
  const fwd = useTeamForward()
  const [mode, setMode] = React.useState<'existing' | 'new'>('existing')
  const [session, setSession] = React.useState('')
  const [path, setPath] = React.useState('')
  const [title, setTitle] = React.useState('')
  const [text, setText] = React.useState('')
  React.useEffect(() => {
    if (!open) return
    setText(initialText)
    setTitle(suggestedTitle)
  }, [open, initialText, suggestedTitle])
  const recent = React.useMemo(() => [...(sessions || [])].sort((a, b) => b.updated - a.updated), [sessions])
  React.useEffect(() => {
    if (open && !session && recent[0]) setSession(recent[0].id)
    if (open && !path && topics[0]) setPath(topics.find((x) => x.path === 'general/inbox')?.path || topics[0].path)
  }, [open, recent, topics, session, path])

  const ok = text.trim() && (mode === 'existing' ? !!session : !!path)
  const submit = () => {
    if (!message || !ok) return
    fwd.mutate(
      { cid: chatId, mid: message.id, text: text.trim(), ...(mode === 'existing' ? { session } : { path, title: title.trim() || undefined }) },
      {
        onSuccess: (r) => {
          onOpenChange(false)
          toast.action(t('team.fwd.sent'), r.session.title, { label: t('team.fwd.open'), onClick: () => navigate(`/sessions/${r.session.id}`) })
        },
      },
    )
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="md:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('team.fwd.title')}</DialogTitle>
          <DialogDescription>{t('team.fwd.desc')}</DialogDescription>
        </DialogHeader>
        <Segmented
          value={mode}
          onChange={setMode}
          options={[
            { value: 'existing', label: t('team.fwd.existing'), icon: <MessagesSquare className="size-3.5" /> },
            { value: 'new', label: t('team.fwd.new'), icon: <MessageSquarePlus className="size-3.5" /> },
          ]}
        />
        {mode === 'existing' ? (
          <div className="flex flex-col gap-1.5">
            <Label>{t('team.fwd.session')}</Label>
            <Combobox
              value={session}
              onChange={setSession}
              options={() => recent.map((s) => ({ value: s.id, label: s.title || s.id, hint: s.path }))}
              labelOf={(v) => recent.find((s) => s.id === v)?.title || ''}
              placeholder={t('team.fwd.pickSession')}
              searchPlaceholder={t('team.fwd.searchSession')}
            />
          </div>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label>{t('team.fwd.topic')}</Label>
              <Combobox
                value={path}
                onChange={setPath}
                options={() => topics.map((x) => ({ value: x.path, label: x.path }))}
                placeholder={t('team.fwd.pickTopic')}
                searchPlaceholder={t('team.fwd.searchTopic')}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="fwd-title">{t('team.fwd.sessionTitle')}</Label>
              <Input id="fwd-title" value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
          </div>
        )}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="fwd-text">{t('team.fwd.text')}</Label>
          <Textarea id="fwd-text" value={text} onChange={(e) => setText(e.target.value)} minRows={5} maxRows={14} className="font-mono text-[12.5px]" />
          <p className="text-[12px] text-muted-foreground">{t('team.fwd.hint')}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={!ok} loading={fwd.isPending}>
            {mode === 'existing' ? t('team.fwd.send') : t('team.fwd.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ------------------------------------------------------------------------------------------------ poll */
export function PollDialog({ open, onOpenChange, chatId }: { open: boolean; onOpenChange: (o: boolean) => void; chatId: string }) {
  const t = useT()
  const create = useTeamPoll()
  const [multi, setMulti] = React.useState(false)
  const [question, setQuestion] = React.useState('')
  const [options, setOptions] = React.useState<string[]>(['', ''])
  React.useEffect(() => {
    if (open) {
      setQuestion('')
      setOptions(['', '', ''])
      setMulti(false)
    }
  }, [open])
  const filled = options.filter((o) => o.trim())
  const ok = question.trim() && filled.length >= 2
  const submit = () => ok && create.mutate({ cid: chatId, question: question.trim(), options: filled, multi }, { onSuccess: () => onOpenChange(false) })
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('team.poll.new')}</DialogTitle>
          <DialogDescription>{t('team.poll.desc')}</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="poll-q">{t('team.poll.question')}</Label>
          <Input id="poll-q" value={question} onChange={(e) => setQuestion(e.target.value)} placeholder={t('team.poll.questionPh')} autoFocus />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label>{t('team.poll.options')}</Label>
          {options.map((o, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className={cn('size-4 shrink-0 border border-muted-foreground/40', multi ? 'rounded-[4px]' : 'rounded-full')} />
              <Input
                value={o}
                onChange={(e) => setOptions(options.map((x, j) => (j === i ? e.target.value : x)))}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault()
                    if (i === options.length - 1 && options.length < 12) setOptions([...options, ''])
                  }
                }}
                placeholder={t('team.poll.optionPh', { n: i + 1 })}
              />
              <Button size="icon-sm" variant="ghost" onClick={() => setOptions(options.filter((_, j) => j !== i))} disabled={options.length <= 2} aria-label={t('common.delete')}>
                <Trash2 className="size-3.5" />
              </Button>
            </div>
          ))}
          <Button variant="ghost" size="sm" className="self-start" onClick={() => setOptions([...options, ''])} disabled={options.length >= 12}>
            <Plus /> {t('team.poll.add')}
          </Button>
        </div>
        <label className="flex cursor-pointer items-center gap-2.5 text-[13.5px]">
          <Checkbox checked={multi} onCheckedChange={(v) => setMulti(!!v)} />
          {t('team.poll.allowMulti')}
        </label>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={!ok} loading={create.isPending}>
            {t('team.poll.create')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/* ------------------------------------------------------------------------------------------------ new chat */
export function NewChatDialog({
  open, onOpenChange, team, onCreated, onConnect,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  team: TeamState | undefined
  onCreated: (id: string) => void
  onConnect: () => void
}) {
  const t = useT()
  const create = useTeamCreateChat()
  const [kind, setKind] = React.useState<'dm' | 'group'>('dm')
  const [members, setMembers] = React.useState<string[]>([])
  const [name, setName] = React.useState('')
  const [emoji, setEmoji] = React.useState('')
  React.useEffect(() => {
    if (open) {
      setMembers([])
      setName('')
      setEmoji('')
    }
  }, [open])
  // contacts only (people met in a group but not connected with are not offered)
  const people = Object.entries(team?.people || {}).filter(([id, p]) => id !== team?.me && p.contact)
  const toggle = (id: string) => setMembers(kind === 'dm' ? [id] : members.includes(id) ? members.filter((m) => m !== id) : [...members, id])
  const ok = members.length > 0 && (kind === 'dm' || name.trim())
  const submit = () =>
    ok &&
    create.mutate(
      { kind, members, name: name.trim(), emoji: emoji.trim() },
      {
        onSuccess: (c) => {
          onOpenChange(false)
          onCreated(c.id)
        },
      },
    )
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t('team.new')}</DialogTitle>
          <DialogDescription>{t('team.newDesc')}</DialogDescription>
        </DialogHeader>
        <Segmented
          value={kind}
          onChange={(k) => {
            setKind(k)
            setMembers(members.slice(0, k === 'dm' ? 1 : undefined))
          }}
          options={[
            { value: 'dm', label: t('team.dm'), icon: <MessagesSquare className="size-3.5" /> },
            { value: 'group', label: t('team.group'), icon: <Users className="size-3.5" /> },
          ]}
        />
        {kind === 'group' && (
          <div className="flex gap-2">
            <Input value={emoji} onChange={(e) => setEmoji(e.target.value)} placeholder="🚀" className="w-14 text-center" maxLength={8} aria-label="Emoji" />
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('team.groupName')} />
          </div>
        )}
        <div className="flex flex-col gap-1">
          {people.map(([id, p]) => {
            const on = members.includes(id)
            return (
              <button
                key={id}
                type="button"
                onClick={() => toggle(id)}
                className={cn('flex items-center gap-3 rounded-lg border px-3 py-2 text-left transition-colors hover:bg-accent/50', on && 'border-primary/60 bg-primary/5')}
              >
                <Avatar profile={p} />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] font-medium">{p.name}</span>
                  <span className="block truncate text-[12px] text-muted-foreground">{p.server}</span>
                </span>
                {on && <Check className="size-4 text-primary" />}
              </button>
            )
          })}
          {!people.length && <p className="py-4 text-center text-[13px] text-muted-foreground">{t('team.noPeople')}</p>}
        </div>
        <button
          type="button"
          onClick={() => {
            onOpenChange(false)
            onConnect()
          }}
          className="flex items-center gap-2 self-start text-[12.5px] font-medium text-primary hover:underline"
        >
          <UserPlus className="size-3.5" /> {t('team.cx.open')}
        </button>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t('common.cancel')}
          </Button>
          <Button onClick={submit} disabled={!ok} loading={create.isPending}>
            {t('team.start')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
