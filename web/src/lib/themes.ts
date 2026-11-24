// Installed themes (<workspace>/themes/<id>/theme.json, server/maxxing/themes.py): values of the interface's
// variables per mode, on top of a built-in theme (Solid or Glass). The server sends them checked and cleaned; here
// they become one <style id="mx-theme"> of rules on html[data-theme-id]: what a theme leaves out keeps the built-in
// value. The CSS is kept in the UI store (`customTheme`) so index.html applies it before the first paint.
import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import type { Accent, Density, Material, Theme, Tint } from '@/stores/ui'
import type { MonoFont, SansFont } from '@/lib/fonts'

export type Label = string | Record<string, string>
export type InstalledTheme = {
  id: string
  name: Label
  description: Label
  author: string
  version: string
  homepage: string
  base: Material
  modes: ('light' | 'dark')[]
  light: Record<string, string>
  dark: Record<string, string>
  options: Partial<{ mode: Theme; accent: Accent; tint: Tint; font: SansFont; mono: MonoFont; density: Density }>
  own_accent: boolean
  own_surfaces: boolean
  wallpaper: { light: string | null; dark: string | null }
  preview: string | null
  warnings: string[]
}
export type ThemeList = { themes: InstalledTheme[]; errors: { id: string; error: string }[] }

/** What the store keeps of the theme in use: enough to paint it before the app loads. */
export type ThemeLook = { id: string; base: Material; mode: 'light' | 'dark' | null; css: string; ownAccent: boolean; ownSurfaces: boolean }

export const label = (l: Label, lang: string) => (typeof l === 'string' ? l : l[lang] || l.en || Object.values(l)[0] || '')

const SAFE = /^[^;{}<>\\"'`@!]*$/
const ID = /^[a-z0-9][a-z0-9-]{1,39}$/

function rules(sel: string, vars: Record<string, string>, wall: string | null): string {
  const body = Object.entries(vars)
    .filter(([k, v]) => /^[a-z0-9-]+$/.test(k) && SAFE.test(v) && !/url\(/i.test(v))
    .map(([k, v]) => `--${k}:${v};`)
  if (wall && /^\/api\/themes\/[a-z0-9-]+\/file\/[A-Za-z0-9._-]+$/.test(wall)) body.push(`--wall:url("${wall}") center / cover no-repeat;`)
  return body.length ? `${sel}{${body.join('')}}` : ''
}

export function themeLook(t: InstalledTheme): ThemeLook | null {
  if (!ID.test(t.id)) return null
  const sel = (dark: boolean) => `html${dark ? '.dark' : ':not(.dark)'}[data-theme-id="${t.id}"]`
  const css = [rules(sel(false), t.light, t.base === 'glass' ? t.wallpaper.light : null), rules(sel(true), t.dark, t.base === 'glass' ? t.wallpaper.dark : null)].join('\n')
  return { id: t.id, base: t.base, mode: t.modes.length === 1 ? t.modes[0] : null, css, ownAccent: t.own_accent, ownSurfaces: t.own_surfaces }
}

export function applyThemeCss(look: ThemeLook | null) {
  let el = document.getElementById('mx-theme') as HTMLStyleElement | null
  if (!look) return el?.remove()
  if (!el) {
    el = document.createElement('style')
    el.id = 'mx-theme'
    document.head.appendChild(el)
  }
  if (el.textContent !== look.css) el.textContent = look.css
}

export function useInstalledThemes(enabled = true) {
  return useQuery({ queryKey: ['themes'], queryFn: () => api.get<ThemeList>('/api/themes'), enabled, staleTime: 60_000 })
}
