// "Send to" a friend or a group, from a session message's menu (right click / long press): the text, editable, goes
// to the Team chat - the direct chat is created on the first message.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Send } from 'lucide-react'
import { useSettings, useTeam, useTeamCreateChat, useTeamSend } from '@/lib/queries'
import { useT } from '@/i18n'
import {
  Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, DropdownMenuSub,
  DropdownMenuSubContent, DropdownMenuSubTrigger, Textarea, toast,
} from '@/components/ui'
import { useCompact } from '@/stores/media'
import { ChatAvatar, chatTitle, friendsOf, PersonAvatar } from './people'

/** A friend (person id: their direct chat, created if needed) or a group (chat id). */
export type SendTarget = { person: string; name: string } | { chat: string; name: string }

const TEXT_MAX = 8000 // team.TEXT_MAX

/** The "Send to" sub-menu: friends (online first), then the groups still open. Nothing when Team is off or empty.
 *  On touch the menu is a full-width sheet with no room beside it: the targets are listed in it instead. */
export function SendToSub({ onPick }: { onPick: (target: SendTarget) => void }) {
  const t = useT()
  const compact = useCompact()
  const { data: s } = useSettings()
  const { data: team } = useTeam(!!s?.team_page)
  if (!s?.team_page || !team) return null
  const friends = friendsOf(team)
  const groups = team.chats.filter((c) => c.kind === 'group' && !c.left)
  if (!friends.length && !groups.length) return null
  const items = (
    <>
      {friends.map(([id, p]) => (
        <DropdownMenuItem key={id} onSelect={() => onPick({ person: id, name: p.name })}>
          <PersonAvatar person={p} size="sm" status /> <span className="truncate">{p.name}</span>
        </DropdownMenuItem>
      ))}
      {!!friends.length && !!groups.length && <DropdownMenuSeparator />}
      {groups.map((c) => (
        <DropdownMenuItem key={c.id} onSelect={() => onPick({ chat: c.id, name: chatTitle(team, c) })}>
          <ChatAvatar team={team} chat={c} size="md" /> <span className="truncate">{chatTitle(team, c)}</span>
        </DropdownMenuItem>
      ))}
    </>
  )
  if (compact)
    return (
      <>
        <DropdownMenuSeparator />
        <DropdownMenuLabel data-testid="msg-send-to" className="flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <Send className="size-3.5" /> {t('sessions.msg.sendTo')}
        </DropdownMenuLabel>
        {items}
      </>
    )
  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger data-testid="msg-send-to">
        <Send /> {t('sessions.msg.sendTo')}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="max-h-80 min-w-48 overflow-y-auto">{items}</DropdownMenuSubContent>
    </DropdownMenuSub>
  )
}

export function SendToDialog({ target, text: initial, onClose }: { target: SendTarget | null; text: string; onClose: () => void }) {
  const t = useT()
  const navigate = useNavigate()
  const create = useTeamCreateChat()
  const send = useTeamSend()
  const [text, setText] = React.useState('')
  React.useEffect(() => {
    if (target) setText(initial.trim().slice(0, TEXT_MAX))
  }, [target, initial])
  const busy = create.isPending || send.isPending
  const submit = async () => {
    if (!target || !text.trim() || busy) return
    try {
      const cid = 'chat' in target ? target.chat : (await create.mutateAsync({ kind: 'dm', members: [target.person] })).id
      await send.mutateAsync({ cid, text: text.trim() })
      onClose()
      toast.action(t('team.sendTo.sent', { name: target.name }), undefined, { label: t('team.fwd.open'), onClick: () => navigate(`/team?chat=${encodeURIComponent(cid)}`) })
    } catch {
      // the mutation's toast says why; the dialog stays open
    }
  }
  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="md:max-w-xl">
        <DialogHeader>
          <DialogTitle>{t('team.sendTo.title', { name: target?.name || '' })}</DialogTitle>
          <DialogDescription>{t('team.sendTo.desc')}</DialogDescription>
        </DialogHeader>
        <Textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          maxLength={TEXT_MAX}
          minRows={5}
          maxRows={14}
          className="text-[13px]"
          data-testid="send-to-text"
          onKeyDown={(e) => {
            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
              e.preventDefault()
              void submit()
            }
          }}
        />
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button onClick={() => void submit()} disabled={!text.trim()} loading={busy} data-testid="send-to-send">
            <Send /> {t('team.fwd.send')}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
