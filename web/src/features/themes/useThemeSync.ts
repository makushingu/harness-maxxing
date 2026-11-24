// Keeps the installed theme in use up to date: changed on the server (Claude edited or reinstalled it) -> its new
// CSS (and its advanced CSS switched off after an update, back on once Claude verified it); removed -> back to its base (Solid or Glass). Only asks the server when a theme is in use.
import * as React from 'react'
import { useUI } from '@/stores/ui'
import { themeLook, useInstalledThemes } from '@/lib/themes'

export function useThemeSync() {
  const id = useUI((s) => s.customTheme?.id ?? null)
  const { data } = useInstalledThemes(!!id)
  React.useEffect(() => {
    if (!id || !data) return
    const t = data.themes.find((x) => x.id === id) ?? null
    const cur = useUI.getState().customTheme
    // gone: back to its base; listed in errors (being edited or reinstalled): keep the last good look
    if (!t) return data.errors.some((e) => e.id === id) ? undefined : useUI.getState().refreshTheme(null)
    const next = themeLook(t)
    if (!cur || !next || next.css !== cur.css || next.extra !== cur.extra || next.cssState !== cur.cssState || next.base !== cur.base || next.mode !== cur.mode || next.ownAccent !== cur.ownAccent || next.ownSurfaces !== cur.ownSurfaces || JSON.stringify(next.logo) !== JSON.stringify(cur.logo)) useUI.getState().refreshTheme(t)
  }, [id, data])
}
