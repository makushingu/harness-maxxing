import * as React from 'react'
import { useNavigation } from 'react-router'

/**
 * Thin top progress bar while a lazy route chunk loads. The previous page stays on screen meanwhile
 * (data router), so navigation never flashes a blank page. Shown only after 120 ms.
 */
export function RouteProgress() {
  const nav = useNavigation()
  const busy = nav.state !== 'idle'
  const [show, setShow] = React.useState(false)
  React.useEffect(() => {
    if (!busy) {
      setShow(false)
      return
    }
    const id = setTimeout(() => setShow(true), 120)
    return () => clearTimeout(id)
  }, [busy])
  return (
    <div aria-hidden className="pointer-events-none fixed inset-x-0 top-0 z-[70] h-0.5 overflow-hidden">
      <div className={`h-full bg-primary transition-[width,opacity] ease-out ${show ? 'w-4/5 opacity-100 duration-[2000ms]' : 'w-full opacity-0 duration-300'}`} />
    </div>
  )
}
