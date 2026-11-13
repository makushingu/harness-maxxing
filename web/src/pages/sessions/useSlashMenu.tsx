// The "/" menu of a message box without an "@" menu (an agent's conversation): the same commands, keys and picks
// as the session composer's (Composer.tsx keeps its own, shared with its "@" menu).
import * as React from 'react'
import { SlashMenu, slashAction, slashItems, type SlashCommand } from './SlashMenu'

export function useSlashMenu({
  text,
  setText,
  commands,
  input,
}: {
  text: string
  setText: (text: string) => void
  /** none: "/" is plain text */
  commands?: SlashCommand[]
  input: React.RefObject<HTMLTextAreaElement | null>
}) {
  // open while the text is "/name" (or "/name value" for a command with values), closed by Esc until the text changes
  const [off, setOff] = React.useState<string | null>(null)
  const [expanded, setExpanded] = React.useState<string[]>([])
  const menu = commands && off !== text ? slashItems(text, commands, expanded) : null
  const [at, setAt] = React.useState(0)
  const menuKey = menu ? `${menu.stage}:${menu.items.map((i) => i.key).join('|')}` : ''
  React.useEffect(() => {
    if (!menu && expanded.length) setExpanded([]) // folded again the next time the menu opens
  }, [!!menu]) // eslint-disable-line react-hooks/exhaustive-deps
  const keepAt = React.useRef<number | null>(null)
  React.useEffect(() => {
    setAt(keepAt.current ?? 0)
    keepAt.current = null
  }, [menuKey])
  const active = menu?.items.length ? Math.min(at, menu.items.length - 1) : 0
  const focusEnd = () =>
    requestAnimationFrame(() => {
      const el = input.current
      if (!el) return
      el.focus({ preventScroll: true })
      el.setSelectionRange(el.value.length, el.value.length)
    })
  const pick = (i: number, complete = false) => {
    const it = menu?.items[i]
    if (!it) return
    const c = it.cmd
    if (it.expand) {
      const g = it.expand
      keepAt.current = i
      setExpanded((cur) => [...cur, g]) // "+ N more": the group unfolds, the selection stays on the same place
      return
    }
    if (menu!.stage === 'arg') {
      setText('')
      c.run?.(it.arg ?? '')
    } else if (!complete && c.kind === 'action' && c.run && !c.args?.length && !c.freeArg) {
      setText('')
      c.run('')
    } else setText(`/${c.name} `)
    focusEnd()
  }
  /** The keys of the open menu -> true when the key was its own (the box does nothing more with it). */
  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): boolean => {
    if (!menu || e.nativeEvent.isComposing) return false
    const n = menu.items.length
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setAt((active + (e.key === 'ArrowDown' ? 1 : n - 1)) % n)
      return true
    }
    if (e.key === 'Tab' && !e.shiftKey) {
      e.preventDefault()
      pick(active, true)
      return true
    }
    if (e.key === 'Enter' && !e.shiftKey && !e.metaKey && !e.ctrlKey) {
      // the name typed in full with nothing to choose: Enter sends it as usual ("/skill" goes to Claude)
      const exact = menu.stage === 'name' && menu.items[active].label === text.trim() && menu.items[active].cmd.kind === 'skill'
      if (!exact) {
        e.preventDefault()
        pick(active)
        return true
      }
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      setOff(text)
      return true
    }
    return false
  }
  /** Before a send: a command typed in full ("/model opus") runs instead -> true when it did (nothing to send). */
  const runTyped = (): boolean => {
    const act = commands ? slashAction(text, commands) : null
    if (!act) return false
    if ((act.cmd.args?.length || act.cmd.freeArg) && !act.arg) setText(`/${act.cmd.name} `) // asks for its value
    else {
      setText('')
      act.cmd.run!(act.arg)
    }
    return true
  }
  const node = menu ? <SlashMenu items={menu.items} active={active} stage={menu.stage} onPick={(i) => pick(i)} onHover={setAt} chat /> : null
  return { node, onKeyDown, runTyped }
}
