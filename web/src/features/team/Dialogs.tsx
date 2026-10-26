// Team dialogs: send a message to a session, create a poll, start a chat.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Check, MessageSquarePlus, MessagesSquare, Plus, Trash2, UserPlus, X } from 'lucide-react'
import { useSessions, useTeamCreateChat, useTeamForward, useTeamPoll, useTopics, type TeamMessage, type TeamState } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Button, Checkbox, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Label, Segmented, Textarea, toast } from '@/components/ui'
import { Combobox } from '@/components/ui/combobox'
import { Avatar } from '@/features/profile/Avatar'
import { friendsOf, PersonAvatar, personOf, usePresence } from './people'

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
/** Pick friends: one = a direct chat, several = a group (its name and emoji are optional). */
export function NewChatDialog({
  open, onOpenChange, team, onCreated, onAddFriend,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  team: TeamState | undefined
  onCreated: (id: string) => void
  onAddFriend: () => void
}) {
  const t = useT()
  const presence = usePresence()
  const create = useTeamCreateChat()
  const [members, setMembers] = React.useState<string[]>([])
  const [q, setQ] = React.useState('')
  const [name, setName] = React.useState('')
  const [emoji, setEmoji] = React.useState('')
  React.useEffect(() => {
    if (open) {
      setMembers([])
      setQ('')
      setName('')
      setEmoji('')
    }
  }, [open])
  const all = friendsOf(team)
  const shown = all.filter(([, p]) => !q || p.name.toLowerCase().includes(q.toLowerCase()))
  const group = members.length > 1
  const toggle = (id: string) => setMembers(members.includes(id) ? members.filter((m) => m !== id) : [...members, id])
  const submit = () =>
    members.length &&
    create.mutate(
      { kind: group ? 'group' : 'dm', members, name: group ? name.trim() : '', emoji: group ? emoji.trim() : '' },
      {
        onSuccess: (c) => {
          onOpenChange(false)
          onCreated(c.id)
        },
      },
    )
  const addFriend = () => {
    onOpenChange(false)
    onAddFriend()
  }
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="gap-3">
        <DialogHeader>
          <DialogTitle>{t('team.new')}</DialogTitle>
          <DialogDescription>{t('team.newDesc')}</DialogDescription>
        </DialogHeader>
        {!all.length ? (
          <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed px-4 py-8 text-center">
            <UserPlus className="size-6 text-muted-foreground" />
            <p className="text-[13px] text-muted-foreground">{t('team.friends.noneDesc')}</p>
            <Button onClick={addFriend}>
              <UserPlus /> {t('team.friends.add')}
            </Button>
          </div>
        ) : (
          <>
            {members.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {members.map((id) => {
                  const p = personOf(team, id)
                  return (
                    <button
                      key={id}
                      type="button"
                      onClick={() => toggle(id)}
                      className="inline-flex items-center gap-1.5 rounded-full border bg-accent/50 py-0.5 pr-1.5 pl-0.5 text-[12.5px] font-medium hover:bg-accent"
                    >
                      <Avatar profile={p} size="sm" />
                      {p.name}
                      <X className="size-3 text-muted-foreground" />
                    </button>
                  )
                })}
              </div>
            )}
            {all.length > 6 && <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('team.friends.search')} className="h-8 text-[13px]" autoFocus />}
            <div className="-mx-1 flex max-h-[min(50vh,360px)] flex-col gap-0.5 overflow-y-auto px-1">
              {shown.map(([id, p]) => {
                const on = members.includes(id)
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => toggle(id)}
                    className={cn('flex items-center gap-3 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-accent/60', on && 'bg-primary/[0.06] hover:bg-primary/10')}
                  >
                    <PersonAvatar person={p} status />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[14px] font-medium">{p.name}</span>
                      <span className="block truncate text-[12px] text-muted-foreground">{presence(p)}</span>
                    </span>
                    <span
                      className={cn(
                        'inline-flex size-5 shrink-0 items-center justify-center rounded-full border transition-colors',
                        on ? 'border-primary bg-primary text-primary-foreground' : 'border-muted-foreground/40',
                      )}
                    >
                      {on && <Check className="size-3" strokeWidth={3} />}
                    </span>
                  </button>
                )
              })}
              {!shown.length && <p className="py-4 text-center text-[13px] text-muted-foreground">{t('team.friends.noMatch')}</p>}
            </div>
            {group && (
              <div className="flex gap-2 animate-in fade-in-0 slide-in-from-top-1">
                <Input value={emoji} onChange={(e) => setEmoji(e.target.value)} placeholder="🚀" className="w-14 text-center" maxLength={8} aria-label="Emoji" />
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={t('team.groupNameOptional')} />
              </div>
            )}
          </>
        )}
        <DialogFooter className="items-center sm:justify-between">
          <button type="button" onClick={addFriend} className="flex items-center gap-1.5 text-[12.5px] font-medium text-primary hover:underline max-sm:order-last">
            <UserPlus className="size-3.5" /> {t('team.friends.add')}
          </button>
          {all.length > 0 && (
            <Button onClick={submit} disabled={!members.length} loading={create.isPending}>
              {!members.length
                ? t('team.pickPeople')
                : group
                  ? t('team.createGroup', { count: members.length + 1 })
                  : t('team.writeTo', { name: personOf(team, members[0]).name })}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
