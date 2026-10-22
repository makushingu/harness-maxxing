// Tiny typed i18n. Add a key to en.ts, then to fr.ts (TypeScript fails until both have it).
// Usage: const t = useT(); t('nav.sessions'); t('common.items', { count: 3 })
// Each language is split into chunks at build time (`i18nSplit` in vite.config.ts): the core, which main.tsx waits
// for before the first render (no flash of another language), and the groups of groups.ts, loaded with the routes
// that declare them (routes.tsx) or, failing that, on the first key asked from them. fr.ts has every key of en.ts
// (TypeScript), so a French page never downloads the English dictionary; English is loaded as the fallback only
// if the active one fails to load.
import { useCallback, useSyncExternalStore } from 'react'
import { loaders } from 'virtual:i18n-loaders'
import { useUI } from '@/stores/ui'
import type { Language } from '@/lib/types'
import type { en } from './en'
import { GROUPS, type Group } from './groups'

export type TKey = keyof typeof en
export type TVars = Record<string, string | number>
export type TFn = (key: TKey, vars?: TVars) => string
type Part = Group | 'core'

const groupOf = new Map<string, Group>()
for (const [g, names] of Object.entries(GROUPS) as [Group, readonly string[]][]) for (const n of names) groupOf.set(n, g)
const partOf = (key: string): Part => groupOf.get(key.split('.', 1)[0]) ?? 'core'

const dicts: Partial<Record<Language, Record<string, string>>> = {}
const loaded = new Set<string>() // `${lang}:${part}`
const pending = new Map<string, Promise<void>>()
const failed = new Map<string, number>() // `${lang}:${part}` -> when it last failed: translate() runs on every render
const RETRY_MS = 30_000
let version = 0
const listeners = new Set<() => void>()
const subscribe = (cb: () => void) => {
  listeners.add(cb)
  return () => listeners.delete(cb)
}

/** Loads one chunk of a language (once); `useT` re-renders when it arrives. Never rejects: when it cannot be
 * loaded, the English one is loaded instead (retried on a call 30 s later at the earliest). */
function loadPart(lang: Language, part: Part): Promise<void> {
  const id = `${lang}:${part}`
  if (loaded.has(id)) return Promise.resolve()
  const at = failed.get(id)
  if (at !== undefined && Date.now() - at < RETRY_MS) return lang !== 'en' ? loadPart('en', part) : Promise.resolve()
  let p = pending.get(id)
  if (!p) {
    const load = loaders[lang]?.[part]
    p = (load ? load() : Promise.reject(new Error(`no dictionary for ${id}`)))
      .then((m) => {
        dicts[lang] = Object.assign(dicts[lang] ?? {}, m.default)
        loaded.add(id)
        failed.delete(id)
        version++
        listeners.forEach((cb) => cb())
      })
      .catch(() => {
        pending.delete(id)
        failed.set(id, Date.now())
        if (lang !== 'en') return loadPart('en', part)
      })
    pending.set(id, p)
  }
  return p
}

/** Loads the core dictionary of a language. */
export function loadLanguage(lang: Language): Promise<void> {
  return loadPart(lang, 'core')
}

/** Loads dictionary groups (groups.ts) of the current language, e.g. with a page chunk. */
export function loadGroups(groups: readonly Group[]): Promise<void> {
  const lang = useUI.getState().language
  return Promise.all(groups.map((g) => loadPart(lang, g))).then(() => undefined)
}

/** Wraps a lazy import so that it resolves once the dictionary groups it needs are there too. */
export function withGroups<T>(groups: readonly Group[], load: () => Promise<T>): () => Promise<T> {
  return () => Promise.all([load(), loadGroups(groups)]).then(([m]) => m)
}

export function translate(lang: Language, key: TKey, vars?: TVars): string {
  // While a newly picked language (or a group) is still downloading, the one already on screen stays: never raw keys.
  const part = partOf(key)
  if (!loaded.has(`${lang}:${part}`)) void loadPart(lang, part)
  const d = dicts[lang]?.[key] !== undefined ? dicts[lang] : (Object.values(dicts).find((x) => x?.[key] !== undefined) ?? dicts[lang])
  const count = vars?.count
  const one = typeof count === 'number' && (lang === 'fr' ? count <= 1 : count === 1)
  const pk = `${key}#one`
  const busy = (l: Language) => pending.has(`${l}:${part}`) && !loaded.has(`${l}:${part}`)
  let s = (one && d?.[pk]) || d?.[key] || (busy(lang) || busy('en') ? '' : key)
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.split(`{${k}}`).join(String(v))
  return s
}

export function useT(): TFn {
  const lang = useUI((s) => s.language)
  const v = useSyncExternalStore(subscribe, () => version)
  // eslint-disable-next-line react-hooks/exhaustive-deps -- `v`: a new function once the dictionary has arrived
  return useCallback((key, vars) => translate(lang, key, vars), [lang, v])
}

export function useLang(): Language {
  return useUI((s) => s.language)
}

/** Untyped lookup for dynamic keys (e.g. `settings.section.${id}`); falls back to `fallback`. */
export function tDyn(t: TFn, key: string, fallback?: string): string {
  const v = t(key as TKey)
  return !v || v === key ? (fallback ?? key) : v // '' while its group downloads
}

export const LANGUAGES: { id: Language; label: string }[] = [
  { id: 'en', label: 'English' },
  { id: 'fr', label: 'Français' },
]
