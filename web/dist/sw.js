/* Harness Maxxing service worker — hand-written, no dependency.
 * Built by the `maxxing-sw` Vite plugin (vite.config.ts): the VERSION and PRECACHE placeholders are replaced at
 * build time, so every build gets its own cache names and the browser sees a new sw.js (update flow).
 *
 * Strategies
 *   navigations (HTML)      network-first, never cached (index.html is no-store) → offline.html on failure
 *   /assets/* (hashed)      cache-first (immutable), filled at install (app shell) and on demand (lazy chunks)
 *   other static files      stale-while-revalidate (icons, fonts, manifest, favicon)
 *   /api/*, /ext/*, non-GET, cross-origin   never touched (straight to the network)
 *
 * Web Push ("Harness has finished", server/maxxing/webpush.py): the server sends an EMPTY push; the worker then asks
 * POST /api/push/pending (same origin, the app's cookie) what to show, one notification per session; a tap opens it.
 */
const VERSION = "6e61f97b25d2"
const PRECACHE = ["/assets/index-DRRKrTZ9.js","/assets/rolldown-runtime-BLXQ4ufn.js","/assets/vendor-react-3TXWmzc3.js","/assets/ui-DbGKurDi.js","/assets/react-C7xP5ae_.js","/assets/middleware-CpWMw2yu.js","/assets/preload-helper-DdBB-4Xk.js","/assets/vendor-query-CbR4jNTq.js","/assets/media-D9y40YbN.js","/assets/pwa-C6r8wOrj.js","/assets/queries-Cu1T-XLB.js","/assets/toast-DQjWvwds.js","/assets/vendor-ui-BPUi5vFr.js","/assets/upload-DV5YmtB_.js","/assets/createLucideIcon-Bu283v16.js","/assets/utils-ZoX-Tm63.js","/assets/vendor-router-BEU8L7IU.js","/assets/spinner-Dslwyy3S.js","/assets/check-B58vpMO2.js","/assets/sheet-drag-mYxFvavZ.js","/assets/bot-BpoWW4gw.js","/assets/git-branch-CK2BM0Wi.js","/assets/x-Dkb-lCPv.js","/assets/folder-open-CQ4A-W1Q.js","/assets/index-B0lBCXV_.css","/assets/inter-latin-wght-normal-Dx4kXJAl.woff2"]
const SHELL = `mx-shell-${VERSION}`
const ASSETS = `mx-assets-${VERSION}`
const OFFLINE = '/offline.html'

self.addEventListener('install', (event) => {
  event.waitUntil(
    (async () => {
      const shell = await caches.open(SHELL)
      await shell.addAll([OFFLINE, '/manifest.webmanifest', '/favicon.svg', '/icons/icon-192.png'])
      const assets = await caches.open(ASSETS)
      await assets.addAll(PRECACHE)
      // First install: take over immediately. Updates wait for the page to ask (SKIP_WAITING).
      if (!self.registration.active) await self.skipWaiting()
    })(),
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    (async () => {
      const keep = new Set([SHELL, ASSETS])
      for (const k of await caches.keys()) if (k.startsWith('mx-') && !keep.has(k)) await caches.delete(k)
      if (self.registration.navigationPreload) await self.registration.navigationPreload.enable().catch(() => {})
      await self.clients.claim()
    })(),
  )
})

self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') self.skipWaiting()
  if (event.data && event.data.type === 'VERSION') event.ports[0] && event.ports[0].postMessage(VERSION)
})

const bypass = (url) => url.pathname.startsWith('/api/') || url.pathname === '/api' || url.pathname.startsWith('/ext/') || url.pathname === '/sw.js'

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method !== 'GET') return
  const url = new URL(req.url)
  if (url.origin !== self.location.origin || bypass(url)) return

  if (req.mode === 'navigate') {
    event.respondWith(
      (async () => {
        try {
          const preload = await event.preloadResponse
          if (preload) return preload
          return await fetch(req)
        } catch (e) {
          return (await caches.match(OFFLINE)) || new Response('You are offline - the server could not be reached.', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } })
        }
      })(),
    )
    return
  }

  if (url.pathname.startsWith('/assets/')) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(ASSETS)
        const hit = await cache.match(req)
        if (hit) return hit
        const res = await fetch(req)
        if (res.ok && !(res.headers.get('content-type') || '').startsWith('text/html'))
          cache.put(req, res.clone()).catch(() => {})
        return res
      })(),
    )
    return
  }

  // Other same-origin static files (icons, fonts, manifest…): stale-while-revalidate.
  // Anything without a file extension or ending in .html is left to the network (SPA routes, documents).
  if (!/\.[a-z0-9]+$/i.test(url.pathname) || url.pathname.endsWith('.html')) return
  event.respondWith(
    (async () => {
      const cache = await caches.open(SHELL)
      const hit = await cache.match(req)
      const net = fetch(req)
        .then((res) => {
          if (res.ok && res.type === 'basic') cache.put(req, res.clone()).catch(() => {})
          return res
        })
        .catch(() => hit || Response.error())
      if (hit) {
        event.waitUntil(net.catch(() => {}))
        return hit
      }
      return net
    })(),
  )
})

// ---- Web Push --------------------------------------------------------------------------------------------
const deviceId = async (endpoint) => {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint))
  return Array.from(new Uint8Array(h)).map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16)
}

self.addEventListener('push', (event) => {
  event.waitUntil(
    (async () => {
      let items = null // null = the server could not be asked: a generic notification (every push must show one)
      try {
        const sub = await self.registration.pushManager.getSubscription()
        if (sub) {
          const r = await fetch('/api/push/pending', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-Maxxing': '1' },
            body: JSON.stringify({ device: await deviceId(sub.endpoint) }),
          })
          if (r.ok) items = (await r.json()).items || []
        }
      } catch (e) {
        items = null
      }
      if (items && !items.length) return // already shown by a push that came before this one
      // The page being looked at rings by itself (toast), except on iOS where every push must show a notification.
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      if (items && !/iPad|iPhone|iPod/.test(self.navigator.userAgent) && wins.some((c) => c.visibilityState === 'visible' && c.focused)) return
      for (const m of items || [{ title: 'Harness', body: '', url: '/', tag: 'mx-push' }]) {
        await self.registration.showNotification(m.title, {
          body: m.body,
          tag: m.tag || undefined,
          icon: '/icons/icon-192.png',
          badge: '/icons/icon-192.png',
          data: { url: m.url || '/' },
        })
      }
    })(),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin)
  if (url.origin !== self.location.origin) return
  event.waitUntil(
    (async () => {
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const open = wins.find((c) => new URL(c.url).origin === url.origin)
      if (open) {
        await open.focus().catch(() => {})
        if ('navigate' in open) await open.navigate(url.href).catch(() => {})
      } else await self.clients.openWindow(url.href)
    })(),
  )
})
