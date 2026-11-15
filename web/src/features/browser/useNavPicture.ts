// A navigator's small live picture (the profile's /picture of that navigator's tab): a new one every `every` ms, only
// while the page is visible and the browser runs (never started to draw it); the previous one stays until the next.
import * as React from 'react'
import { seg } from '@/lib/api'

export function useNavPicture(pid: string, nav: string, running: boolean, every = 2000, width = 640): string | null {
  const [src, setSrc] = React.useState<string | null>(null)
  React.useEffect(() => {
    setSrc(null)      // the previous profile's picture is revoked by the cleanup: never show it broken
    if (!running || !pid) return
    let stop = false
    let url: string | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    const tick = async () => {
      if (stop) return
      if (document.visibilityState === 'visible') {
        try {
          const r = await fetch(`/api/browser/profiles/${seg(pid)}/picture?w=${width}&nav=${encodeURIComponent(nav)}`, { credentials: 'same-origin', cache: 'no-store' })
          const blob = r.status === 200 && !stop ? await r.blob() : null
          if (blob && !stop) {      // closed while it downloaded: no URL that the cleanup can no longer revoke
            const next = URL.createObjectURL(blob)
            if (url) URL.revokeObjectURL(url)
            url = next
            setSrc(next)
          }
        } catch {
          /* the next one */
        }
      }
      timer = setTimeout(tick, every)
    }
    tick()
    return () => {
      stop = true
      clearTimeout(timer)
      if (url) URL.revokeObjectURL(url)
    }
  }, [running, pid, nav, every, width])
  return src
}
