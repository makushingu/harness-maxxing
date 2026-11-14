// The person's browser in its window, mounted once by the shell: opened by openMyBrowser() from anywhere, closed by
// its "minimize" or when the person goes to another page (a link of its ⋮ menu; not a link that asks for it: ?live=1).
import * as React from 'react'
import { useLocation } from 'react-router'
import { useSettings } from '@/lib/queries'
import { BrowserWindow } from './BrowserWindow'
import { openMyBrowser, useMyBrowserOpen } from './open'

export function MyBrowserWindow() {
  const open = useMyBrowserOpen()
  const { data: s } = useSettings()
  const { pathname, search } = useLocation()
  const at = React.useRef(pathname + search)
  React.useEffect(() => {
    if (at.current !== pathname + search && open && !new URLSearchParams(search).has('live')) openMyBrowser(false)
    at.current = pathname + search
  }, [pathname, search, open])
  if (!s?.browser_feature) return null
  return <BrowserWindow open={open} onOpenChange={openMyBrowser} nav="me" start />
}
