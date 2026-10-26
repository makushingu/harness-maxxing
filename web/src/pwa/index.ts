// PWA runtime: service worker registration + update flow, install prompt capture, iOS detection.
// `initPWA()` runs once from main.tsx (before React) so the early `beforeinstallprompt` event is never missed.
// The worker itself is web/sw/sw.js (emitted as /sw.js by the `maxxing-sw` Vite plugin, production builds only).
import { create } from 'zustand'

/** Chrome's install prompt event (not in lib.dom). */
type BeforeInstallPromptEvent = Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }> }

type PWAState = {
  /** Deferred `beforeinstallprompt` (Android / desktop Chromium): the app can be installed with one click. */
  installEvent: BeforeInstallPromptEvent | null
  /** A new service worker is installed and waiting to take over. */
  waiting: ServiceWorker | null
  /** The "how to install" dialog (no native prompt here: Safari, Firefox, iOS, or Chromium before it offers one). */
  helpOpen: boolean
  setHelpOpen: (o: boolean) => void
  /** Installed during this visit (`appinstalled`): the entries hide. */
  installed: boolean
}

export const usePWA = create<PWAState>((set) => ({
  installEvent: null,
  waiting: null,
  helpOpen: false,
  setHelpOpen: (helpOpen) => set({ helpOpen }),
  installed: false,
}))

export function isStandalone(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
}

/** iPhone / iPad (iPadOS reports itself as a Mac with touch). */
export function isIOS(): boolean {
  const ua = navigator.userAgent
  return /iPad|iPhone|iPod/.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

/** Where the app is opened, for the install steps: each browser installs web apps its own way. */
export type InstallPlatform = 'chrome' | 'edge' | 'safari' | 'firefox' | 'ios' | 'android'
export const INSTALL_PLATFORMS: InstallPlatform[] = ['chrome', 'edge', 'safari', 'firefox', 'ios', 'android']

export function detectPlatform(): InstallPlatform {
  const ua = navigator.userAgent
  if (isIOS()) return 'ios'
  if (/Android/i.test(ua)) return 'android'
  if (/Firefox\//.test(ua)) return 'firefox'
  if (/Edg\//.test(ua)) return 'edge'
  if (/Chrome\/|Chromium\//.test(ua)) return 'chrome'
  if (/Safari\//.test(ua)) return 'safari'
  return 'chrome'
}

/** What the "Install app" entry does here: the browser's own prompt (one click), the steps for this browser,
 *  or nothing when the app is already running installed. */
export function useInstallMode(): 'prompt' | 'guide' | null {
  const ev = usePWA((s) => s.installEvent)
  const installed = usePWA((s) => s.installed)
  if (installed || isStandalone()) return null
  return ev ? 'prompt' : 'guide'
}

export async function installApp() {
  const { installEvent } = usePWA.getState()
  if (installEvent) {
    usePWA.setState({ installEvent: null }) // a deferred prompt can only be used once
    await installEvent.prompt().catch(() => {})
    const choice = await installEvent.userChoice.catch(() => null)
    if (choice?.outcome === 'accepted') usePWA.setState({ installed: true })
    return
  }
  usePWA.getState().setHelpOpen(true)
}

/** Activates the waiting worker; the page reloads on `controllerchange`. */
export function applyUpdate() {
  const w = usePWA.getState().waiting
  if (w) w.postMessage({ type: 'SKIP_WAITING' })
  else location.reload()
}

/** Someone is writing (a message, a file, a field): reloading now would steal the caret. */
function typing() {
  const el = document.activeElement
  return el instanceof HTMLElement && (el.isContentEditable || el.matches('input, textarea, select'))
}

/** A new build is ready while the app is open (Harness was updated): switch to it by itself as soon as nobody
 *  is typing - right away, or when the field loses focus or the tab goes to the background. Until then the
 *  sidebar shows "New version - reload". */
function announceUpdate(w: ServiceWorker) {
  usePWA.setState({ waiting: w })
  if (!typing()) return applyUpdate()
  const later = () => {
    if (document.visibilityState === 'visible' && typing()) return
    document.removeEventListener('focusout', soon)
    document.removeEventListener('visibilitychange', later)
    applyUpdate()
  }
  // focusout fires before the next element takes focus: look once it has
  const soon = () => setTimeout(later, 0)
  document.addEventListener('focusout', soon)
  document.addEventListener('visibilitychange', later)
}

let registration: ServiceWorkerRegistration | null = null
/** Look for a new build now (the server came back after a restart, maybe from an update). */
export function checkForUpdate() {
  registration?.update().catch(() => {})
}

let started = false
export function initPWA() {
  if (started) return
  started = true
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault() // keep it for our own "Install app" entry
    usePWA.setState({ installEvent: e as BeforeInstallPromptEvent })
  })
  window.addEventListener('appinstalled', () => usePWA.setState({ installEvent: null, installed: true, helpOpen: false }))

  if (!import.meta.env.PROD || !('serviceWorker' in navigator) || !window.isSecureContext) return
  let reloading = false
  // The page that is loading came from the network (navigations are network-first), so it is already the
  // newest build: activating a worker that was waiting at load time must not reload it a second time.
  let silentSwap = false
  const hadController = !!navigator.serviceWorker.controller
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    // First install claims the page: no reload. Afterwards a new controller = the user accepted an update.
    if (!hadController || reloading) return
    if (silentSwap) {
      silentSwap = false
      return
    }
    reloading = true
    location.reload()
  })
  const register = async () => {
    try {
      const reg = await navigator.serviceWorker.register('/sw.js', { scope: '/', updateViaCache: 'none' })
      registration = reg
      const track = (w: ServiceWorker | null) => {
        if (!w) return
        w.addEventListener('statechange', () => {
          if (w.state === 'installed' && navigator.serviceWorker.controller) announceUpdate(w)
        })
      }
      // Already waiting when the page loads (the user reloaded after an update): nothing is in progress
      // yet, so switch to the new version right away - without reloading the page that just loaded.
      if (reg.waiting && navigator.serviceWorker.controller) {
        silentSwap = true
        reg.waiting.postMessage({ type: 'SKIP_WAITING' })
      }
      track(reg.installing)
      reg.addEventListener('updatefound', () => track(reg.installing))
      // Look for a new version when the app comes back to the foreground, and every 30 min.
      const check = () => reg.update().catch(() => {})
      document.addEventListener('visibilitychange', () => document.visibilityState === 'visible' && check())
      setInterval(check, 30 * 60_000)
    } catch {
      /* no SW (private mode, blocked): the app works the same, just without offline support */
    }
  }
  if (document.readyState === 'complete') void register()
  else window.addEventListener('load', () => void register(), { once: true })
}
