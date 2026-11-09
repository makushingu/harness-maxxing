// "Capture a zone" of the Feedback dialog: the user drags a rectangle over the page, the browser draws the page into a
// canvas (modern-screenshot, loaded on first use) and keeps that rectangle. Nothing leaves the browser until Send.
import * as React from 'react'
import { createPortal } from 'react-dom'
import { useT } from '@/i18n'

export type Zone = { x: number; y: number; w: number; h: number }
export type Shot = { blob: Blob; mime: string; width: number; height: number; url: string }

const MAX_BYTES = 1000 * 1000           // under the server's 1 MiB (feedback.MAX_IMAGE)
const MAX_SIDE = 2400
const frames = (n: number) => new Promise<void>((ok) => { const f = () => (--n <= 0 ? ok() : requestAnimationFrame(f)); requestAnimationFrame(f) })

/** Full-screen layer to drag the zone on. Esc or right click = cancel, Enter = the whole screen. */
export function ZoneSelect({ onDone }: { onDone: (z: Zone | null) => void }) {
  const t = useT()
  const [start, setStart] = React.useState<{ x: number; y: number } | null>(null)
  const [zone, setZone] = React.useState<Zone | null>(null)
  React.useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); onDone(null) }
      else if (e.key === 'Enter') { e.preventDefault(); onDone({ x: 0, y: 0, w: innerWidth, h: innerHeight }) }
    }
    window.addEventListener('keydown', key, true)
    return () => window.removeEventListener('keydown', key, true)
  }, [onDone])
  const rect = (a: { x: number; y: number }, b: { x: number; y: number }): Zone => ({ x: Math.min(a.x, b.x), y: Math.min(a.y, b.y), w: Math.abs(a.x - b.x), h: Math.abs(a.y - b.y) })
  return createPortal(
    <div
      data-capture-skip
      className="fixed inset-0 cursor-crosshair touch-none select-none"
      style={{ zIndex: 2147483000 }}
      onContextMenu={(e) => { e.preventDefault(); onDone(null) }}
      onPointerDown={(e) => {
        if (e.button !== 0) return
        e.currentTarget.setPointerCapture(e.pointerId)
        setStart({ x: e.clientX, y: e.clientY })
        setZone({ x: e.clientX, y: e.clientY, w: 0, h: 0 })
      }}
      onPointerMove={(e) => { if (start) setZone(rect(start, { x: e.clientX, y: e.clientY })) }}
      onPointerUp={(e) => {
        if (!start) return
        const z = rect(start, { x: e.clientX, y: e.clientY })
        setStart(null)
        if (z.w < 12 || z.h < 12) { setZone(null); return }   // a click, not a drag
        onDone(z)
      }}
    >
      {zone && zone.w > 0 ? (
        <div className="absolute rounded-sm border-2 border-primary" style={{ left: zone.x, top: zone.y, width: zone.w, height: zone.h, boxShadow: '0 0 0 100vmax rgb(0 0 0 / 0.45)' }} />
      ) : (
        <div className="absolute inset-0 bg-black/45" />
      )}
      <div className="pointer-events-none absolute inset-x-0 top-4 flex justify-center px-4">
        <div className="rounded-full bg-popover px-4 py-2 text-center text-sm text-popover-foreground shadow-lg">{t('feedback.zoneHint')}</div>
      </div>
    </div>,
    document.body,
  )
}

/** The page as it is now, cut to `z` (CSS pixels of the viewport), as WebP (else JPEG) of 1 MB at most. */
export async function shootZone(z: Zone): Promise<Shot> {
  const { domToCanvas } = await import('modern-screenshot')
  await frames(2)
  const dpr = Math.min(window.devicePixelRatio || 1, 2)
  const bg = getComputedStyle(document.body).backgroundColor
  const page = await domToCanvas(document.body, {
    width: innerWidth,
    height: innerHeight,
    scale: dpr,
    backgroundColor: bg,
    filter: (n) => !(n instanceof Element && n.hasAttribute('data-capture-skip')),
  })
  let scale = Math.min(1, MAX_SIDE / (Math.max(z.w, z.h) * dpr))
  for (let i = 0; ; i++) {
    const w = Math.max(1, Math.round(z.w * dpr * scale)), h = Math.max(1, Math.round(z.h * dpr * scale))
    const c = document.createElement('canvas')
    c.width = w
    c.height = h
    const g = c.getContext('2d')!
    g.fillStyle = bg
    g.fillRect(0, 0, w, h)
    g.drawImage(page, z.x * dpr, z.y * dpr, z.w * dpr, z.h * dpr, 0, 0, w, h)
    let blob = await new Promise<Blob | null>((ok) => c.toBlob(ok, 'image/webp', 0.9))
    if (!blob || blob.type !== 'image/webp') blob = await new Promise<Blob | null>((ok) => c.toBlob(ok, 'image/jpeg', 0.85))   // Safari: no WebP encoder
    if (!blob) throw new Error('capture failed')
    if (blob.size <= MAX_BYTES || i >= 6) {
      if (blob.size > MAX_BYTES) throw new Error('capture too large')
      return { blob, mime: blob.type, width: w, height: h, url: URL.createObjectURL(blob) }
    }
    scale *= 0.75
  }
}

export const blobBase64 = (b: Blob) =>
  new Promise<string>((ok, fail) => {
    const r = new FileReader()
    r.onload = () => ok(String(r.result).replace(/^data:[^,]*,/, ''))
    r.onerror = () => fail(r.error)
    r.readAsDataURL(b)
  })
