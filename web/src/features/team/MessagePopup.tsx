// New Team messages shown as messages, where the toasts go (Live.tsx): who wrote, what they wrote, and a box to answer
// on the spot. Tapping a message opens its chat. One card holds the chats that just wrote (POPUP_CHATS at most); each
// leaves by itself, never while an answer is being written.
import * as React from 'react'
import { SendHorizontal, X } from 'lucide-react'
import { create } from 'zustand'
import { useTeam, useTeamRead, useTeamSend, type TeamChat, type TeamState } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button, Input, toast } from '@/components/ui'
import { ChatAvatar, chatTitle } from './people'

const STAY_MS = 12_000
/** Messages of one chat shown at most (the latest). */
const POPUP_LINES = 3
const POPUP_CHATS = 3

type Line = { at: number; text: string }
type Popup = { chat: string; lines: Line[]; open: () => void }

const usePopups = create<{ list: Popup[] }>(() => ({ list: [] }))
/** The card on screen (a new one each time: the one that is leaving cannot take a new message with it). */
let card: string | null = null
let cards = 0

/** A message came: its chat joins the card (newest chat first), or gets one more line. */
export function showMessagePopup(chat: string, line: Line, open: () => void) {
  const { list } = usePopups.getState()
  const old = list.find((p) => p.chat === chat)
  usePopups.setState({
    list: old
      ? list.map((p) => (p === old ? { chat, open, lines: [...p.lines, line].slice(-POPUP_LINES) } : p))
      : [{ chat, open, lines: [line] }, ...list].slice(0, POPUP_CHATS),
  })
  place()
}

/** Puts the card in the stack, or has the stack measure it again (its height changes with its chats and lines). */
function place() {
  const id = (card ??= `mx-team-popups-${++cards}`)
  toast.card(
    id,
    () => <MessagePopups />,
    () => {
      if (card !== id) return
      card = null
      usePopups.setState({ list: [] })
    },
  )
}

/** The chat leaves the card (read, answered, closed); the card leaves with its last chat. */
export function dropMessagePopup(chat: string) {
  const { list } = usePopups.getState()
  if (!list.some((p) => p.chat === chat)) return
  const left = list.filter((p) => p.chat !== chat)
  usePopups.setState({ list: left })
  if (left.length) return place()
  if (card) toast.dismiss(card)
  card = null
}

export const messagePopupChats = () => usePopups.getState().list.map((p) => p.chat)

function MessagePopups() {
  const list = usePopups((s) => s.list)
  const { data: team } = useTeam()
  if (!team) return null
  return (
    <div className="w-full max-w-[min(356px,calc(100vw-16px))] divide-y rounded-lg border" data-testid="team-popups">
      {list.map((p) => {
        const chat = team.chats.find((c) => c.id === p.chat)
        return chat && <MessagePopup key={p.chat} team={team} chat={chat} popup={p} />
      })}
    </div>
  )
}

function MessagePopup({ team, chat, popup }: { team: TeamState; chat: TeamChat; popup: Popup }) {
  const t = useT()
  const send = useTeamSend()
  const { mutate: read } = useTeamRead()
  const [text, setText] = React.useState('')
  const [focus, setFocus] = React.useState(false)
  const writing = focus || !!text
  const id = chat.id
  const last = popup.lines[popup.lines.length - 1]?.at
  // STAY_MS on screen (the clock stops while the page is hidden), again from the start for each new message.
  React.useEffect(() => {
    if (writing) return
    let timer = 0
    const arm = () => {
      window.clearTimeout(timer)
      if (!document.hidden) timer = window.setTimeout(() => dropMessagePopup(id), STAY_MS)
    }
    arm()
    document.addEventListener('visibilitychange', arm)
    return () => {
      window.clearTimeout(timer)
      document.removeEventListener('visibilitychange', arm)
    }
  }, [writing, last, id])
  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const v = text.trim()
    if (!v || send.isPending) return
    send.mutate(
      { cid: id, text: v },
      {
        // answered = read: the chat's unread mark goes with its popup
        onSuccess: () => {
          dropMessagePopup(id)
          read(id)
        },
      },
    )
  }
  const title = chatTitle(team, chat)
  return (
    <div className="flex flex-col gap-2.5 p-3" data-testid="team-popup" data-chat={id}>
      <div className="flex items-start gap-1">
        <button
          type="button"
          onClick={() => {
            dropMessagePopup(id)
            popup.open()
          }}
          aria-label={`${t('notify.open')} : ${title}`}
          className="flex min-w-0 flex-1 items-start gap-2.5 rounded-md text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ChatAvatar team={team} chat={chat} />
          <span className="flex min-w-0 flex-1 flex-col items-start gap-1">
            <span className="max-w-full truncate text-[13.5px] font-semibold">{title}</span>
            {popup.lines.map((l) => (
              <span key={l.at} className="max-w-full rounded-2xl rounded-tl-md bg-muted px-3 py-1.5 text-[14px] leading-snug">
                <span className="line-clamp-4 whitespace-pre-wrap [overflow-wrap:anywhere]">{l.text}</span>
              </span>
            ))}
          </span>
        </button>
        <Button size="icon-sm" variant="ghost" className="-mt-1.5 -mr-1.5 shrink-0" onClick={() => dropMessagePopup(id)} aria-label={t('common.close')}>
          <X />
        </Button>
      </div>
      <form onSubmit={submit} className="flex items-center gap-1.5">
        <Input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onFocus={() => setFocus(true)}
          onBlur={() => setFocus(false)}
          placeholder={t('notify.reply')}
          aria-label={t('notify.reply')}
          enterKeyHint="send"
          autoComplete="off"
          className="min-w-0 flex-1 rounded-full px-3.5"
        />
        <Button type="submit" size="icon" className="shrink-0 rounded-full" disabled={!text.trim() || send.isPending} aria-label={t('notify.send')}>
          <SendHorizontal />
        </Button>
      </form>
    </div>
  )
}
