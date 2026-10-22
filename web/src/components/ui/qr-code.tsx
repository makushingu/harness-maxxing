import * as React from 'react'
import { encode } from 'uqr'
import { cn } from '@/lib/utils'

/** QR code drawn as one SVG path (crisp, themable, generated client-side). Always dark-on-white for scanners. */
export function QRCode({ value, className, label }: { value: string; className?: string; label?: string }) {
  const { d, size } = React.useMemo(() => {
    const qr = encode(value, { border: 2, ecc: 'M' })
    let path = ''
    qr.data.forEach((row, y) =>
      row.forEach((on, x) => {
        if (on) path += `M${x} ${y}h1v1h-1z`
      }),
    )
    return { d: path, size: qr.size }
  }, [value])
  return (
    <svg viewBox={`0 0 ${size} ${size}`} className={cn('rounded-lg bg-white', className)} role="img" aria-label={label} shapeRendering="crispEdges">
      <path d={d} fill="#09090b" />
    </svg>
  )
}
