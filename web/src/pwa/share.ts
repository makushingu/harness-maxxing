// What another app shared to the installed one (manifest share_target, kept by the service worker: web/sw/sw.js).
import { isStandalone } from './index'

const SHARE = 'mx-share'

/** The text and the files shared last, once: null when nothing waits. */
export async function takeShare(): Promise<{ text: string; files: File[] } | null> {
  if (!('caches' in window)) return null
  try {
    // Only the installed app is a share target. In a browser tab the same request could come from a form of another
    // site: what it carries is dropped, never typed in a composer.
    if (!isStandalone()) {
      await caches.delete(SHARE)
      return null
    }
    const cache = await caches.open(SHARE)
    const meta = await cache.match('/__share/meta')
    if (!meta) return null
    const m = (await meta.json()) as { text: string; files: { name: string; type: string }[] }
    const files: File[] = []
    for (let i = 0; i < m.files.length; i++) {
      const r = await cache.match(`/__share/${i}`)
      if (r) files.push(new File([await r.blob()], m.files[i].name, { type: m.files[i].type }))
    }
    await caches.delete(SHARE)
    return { text: m.text || '', files }
  } catch {
    return null
  }
}
