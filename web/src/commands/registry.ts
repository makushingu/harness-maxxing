// Command palette registry (⌘K / Ctrl+K).
// Pages contribute commands with `useRegisterCommands('files', [...], [deps])` — they appear while the
// page is mounted. Async providers (search-as-you-type) use `useRegisterProvider`.
import * as React from 'react'
import type { LucideIcon } from 'lucide-react'
import type { NavigateFunction } from 'react-router'
import { create } from 'zustand'

export type CommandContext = { navigate: NavigateFunction; close: () => void }

export type Command = {
  id: string
  title: string
  /** Group heading (translated string). */
  group: string
  icon?: LucideIcon
  /** Secondary text on the right (path, hint). */
  hint?: string
  /** Second line (search excerpt); \u0002…\u0003 marks the matched words. */
  detail?: string
  /** Extra search terms. */
  keywords?: string[]
  /** Display-only shortcut (e.g. ['G', 'S']). */
  shortcut?: string[]
  /** Hide the hint/title in presentation mode (user data). */
  sensitive?: boolean
  perform: (ctx: CommandContext) => void
}

export type CommandProvider = {
  id: string
  group: string
  /** Minimum query length before `search` runs. */
  minQuery?: number
  search: (q: string, signal: AbortSignal) => Promise<Command[]> | Command[]
}

type State = {
  sources: Record<string, Command[]>
  providers: Record<string, CommandProvider>
  open: boolean
  setOpen: (o: boolean) => void
}

export const useCommandStore = create<State>((set) => ({
  sources: {},
  providers: {},
  open: false,
  setOpen: (open) => set({ open }),
}))

export function registerCommands(source: string, cmds: Command[]) {
  useCommandStore.setState((s) => ({ sources: { ...s.sources, [source]: cmds } }))
  return () =>
    useCommandStore.setState((s) => {
      const { [source]: _drop, ...rest } = s.sources
      return { sources: rest }
    })
}

export function registerProvider(p: CommandProvider) {
  useCommandStore.setState((s) => ({ providers: { ...s.providers, [p.id]: p } }))
  return () =>
    useCommandStore.setState((s) => {
      const { [p.id]: _drop, ...rest } = s.providers
      return { providers: rest }
    })
}

/** Register commands while the calling component is mounted. */
export function useRegisterCommands(source: string, cmds: Command[], deps: React.DependencyList) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => registerCommands(source, cmds), [source, ...deps])
}

export function useRegisterProvider(p: CommandProvider, deps: React.DependencyList) {
  // eslint-disable-next-line react-hooks/exhaustive-deps
  React.useEffect(() => registerProvider(p), [p.id, ...deps])
}

export const openPalette = () => useCommandStore.getState().setOpen(true)
