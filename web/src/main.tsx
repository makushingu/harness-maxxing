import { createRoot } from 'react-dom/client'
import '@/styles/globals.css'
import { bindUIToDocument, useUI } from '@/stores/ui'
import { bindCompact } from '@/stores/media'
import { loadLanguage } from '@/i18n'
import { initPWA } from '@/pwa'
import { bootPrefetch } from '@/lib/boot'
import { reloadForUpdate } from '@/lib/updateReload'
import { App, queryClient } from './App'

// A browser that never picked a look takes the server's as soon as the early auth check (index.html) answers,
// before the store's defaults are painted over the look index.html already applied.
const early = useUI.getState().lookChosen ? undefined : window.__mxAuth
const adopted = early?.then((a) => a?.look && useUI.getState().adoptLook(a.look)).catch(() => {})
// No wait when the answer is slow: the defaults show, then Root adopts the look.
void Promise.race([adopted, new Promise((r) => setTimeout(r, 400))]).then(() => bindUIToDocument())
bindCompact()
bootPrefetch(queryClient)
// A part of the app built before an update is gone from the server (a tab left open over `maxxing update`): reload
// once to get the new build instead of an error screen. Once a minute at most (no loop if the server is broken).
window.addEventListener('vite:preloadError', (e) => {
  if (reloadForUpdate()) e.preventDefault()
})
initPWA()
// A language change loads its dictionary (useT re-renders once it is there); the active one is loaded before the
// first render, so a French UI never flashes English.
useUI.subscribe((s) => void loadLanguage(s.language))
void loadLanguage(useUI.getState().language).then(() => {
  window.mxStep?.(2) // boot loader (index.html): the app code runs
  createRoot(document.getElementById('root')!).render(<App />)
})
