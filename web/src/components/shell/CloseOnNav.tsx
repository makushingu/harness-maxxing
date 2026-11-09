// Mounted only while a panel of the sidebar is open: closes it when the page changes. Only then subscribed to the URL,
// so the bar's blocks do not render again on every navigation (a tab switch on the Sessions page changes the URL).
import * as React from 'react'
import { useLocation } from 'react-router'

export function CloseOnNav({ onNav }: { onNav: () => void }) {
  const { pathname } = useLocation()
  const first = React.useRef(pathname)
  React.useEffect(() => {
    if (pathname !== first.current) onNav()
  }, [pathname, onNav])
  return null
}
