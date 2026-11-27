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
 * POST /api/push/pending (same origin, the app's cookie) what to show, one notification per session or per event of
 * the Notifications feed (with its Allow / Deny buttons when it waits for an answer); a tap opens it.
 */
const VERSION = "24dc4396e909"
const PRECACHE = ["/assets/index-DoZjJ-9k.js","/assets/rolldown-runtime-XKyaHtl9.js","/assets/vendor-react-BNCMh3YF.js","/assets/ui-CI4fEnks.js","/assets/react-DurwoXPM.js","/assets/middleware-CpWMw2yu.js","/assets/preload-helper-7y9sWmk5.js","/assets/vendor-query-CjPNRXKi.js","/assets/media-nBf7k7Dt.js","/assets/pwa-Ijo3mTN0.js","/assets/queries-CPHqdJ64.js","/assets/files-DDaG1gMr.js","/assets/toast-BKEOZTqX.js","/assets/vendor-ui-Ww2uvVWZ.js","/assets/upload-C2jW9RCp.js","/assets/createLucideIcon-BESczn8r.js","/assets/utils-BtPbbl_M.js","/assets/vendor-router-D5oKdmts.js","/assets/spinner-T-f3wq6M.js","/assets/chevron-right-CUxMzRCA.js","/assets/check-CMuzREZG.js","/assets/sheet-drag-BXz_JlLz.js","/assets/bot-BXWWT0HQ.js","/assets/git-branch-BFDLcfSG.js","/assets/x-XOpLhFOU.js","/assets/folder-open-CBeClfta.js","/assets/index-BsDPzanP.css","/assets/inter-latin-wght-normal-Dx4kXJAl.woff2"]
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

// Shared to the installed app from another one (manifest share_target: a photo, a file, a link, a text): kept in a
// cache of this browser, then the app opens a new session with it (web/src/pwa/share.ts). Nothing is sent before the
// user sends the message.
const SHARE = 'mx-share'
const keepShare = async (req) => {
  try {
    const form = await req.formData()
    const files = form.getAll('files').filter((f) => f && typeof f === 'object' && 'name' in f).slice(0, 10)
    const words = ['title', 'text', 'url'].map((k) => String(form.get(k) || '').trim()).filter((v, i, a) => v && a.indexOf(v) === i)
    await caches.delete(SHARE)
    const cache = await caches.open(SHARE)
    for (let i = 0; i < files.length; i++) await cache.put(`/__share/${i}`, new Response(files[i]))
    await cache.put('/__share/meta', new Response(JSON.stringify({ text: words.join('\n'), files: files.map((f) => ({ name: f.name || 'file', type: f.type || '' })) })))
  } catch (e) {
    /* nothing kept: the app opens anyway */
  }
  return Response.redirect('/sessions?shared=1', 303)
}

self.addEventListener('fetch', (event) => {
  const req = event.request
  if (req.method === 'POST' && new URL(req.url).origin === self.location.origin && new URL(req.url).pathname === '/share') {
    event.respondWith(keepShare(req))
    return
  }
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
          data: { url: m.url || '/', event: m.event || 0 },
          // the buttons of a request waiting for an answer (Android and computers; an iPhone shows none: a tap opens it)
          ...(m.event && m.actions && m.actions.length ? { actions: m.actions.map((a) => ({ action: a.id, title: a.label })), requireInteraction: true } : {}),
        })
      }
    })(),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const data = event.notification.data || {}
  const url = new URL(data.url || '/', self.location.origin)
  if (url.origin !== self.location.origin) return
  event.waitUntil(
    (async () => {
      // A button (Allow, Deny...): answer the event of the feed from here. Not signed in any more, or it failed:
      // open the app on it instead, the answer is given there.
      if (event.action && data.event) {
        try {
          const r = await fetch(`/api/feed/${data.event}/act/${encodeURIComponent(event.action)}`, {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'X-Maxxing': '1' },
          })
          if (r.ok) return
        } catch (e) {
          /* opened below */
        }
      }
      const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true })
      const open = wins.find((c) => new URL(c.url).origin === url.origin)
      if (open) {
        await open.focus().catch(() => {})
        if ('navigate' in open) await open.navigate(url.href).catch(() => {})
      } else await self.clients.openWindow(url.href)
    })(),
  )
})
