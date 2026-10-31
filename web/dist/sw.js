/* Harness Maxxing service worker — hand-written, no dependency.
 * Built by the `maxxing-sw` Vite plugin (vite.config.ts): the VERSION and PRECACHE placeholders are replaced at
 * build time, so every build gets its own cache names and the browser sees a new sw.js (update flow).
 *
 * Strategies
 *   navigations (HTML)      network-first, never cached (index.html is no-store) → offline.html on failure
 *   /assets/* (hashed)      cache-first (immutable), filled at install (app shell) and on demand (lazy chunks)
 *   other static files      stale-while-revalidate (icons, fonts, manifest, favicon)
 *   /api/*, /ext/*, non-GET, cross-origin   never touched (straight to the network)
 */
const VERSION = "a7cef0c461ad"
const PRECACHE = ["/assets/index-Bjc_Zjc0.js","/assets/rolldown-runtime-hePW80VL.js","/assets/vendor-react-CATZNyVw.js","/assets/createLucideIcon-Bl3st4bB.js","/assets/utils-D4uVgWVJ.js","/assets/vendor-router-B8kuLWb3.js","/assets/vendor-ui-BT-jR2rC.js","/assets/media-BSZD7T9C.js","/assets/vendor-query-CthOliPc.js","/assets/files-Bt8XPwy_.js","/assets/spinner-DHcDatuC.js","/assets/index-BZYe8PT9.css","/assets/inter-latin-wght-normal-Dx4kXJAl.woff2"]
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
