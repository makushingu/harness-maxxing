import * as React from 'react'
import { cn } from '@/lib/utils'
import { EASE_OUT, reducedMotion } from '@/lib/presence'

/** Segmented control (radio group look-alike) for 2-5 exclusive options. Keyboard: arrows. Too wide for its place
 *  (a narrow phone, long labels): the options go on a second line, none is cut. The highlight is one element that
 *  glides from the old option to the new one (transform only; not with reduced motion). */
export function Segmented<T extends string>({
  value,
  onChange,
  options,
  className,
  'aria-label': ariaLabel,
  size = 'default',
}: {
  value: T
  onChange: (v: T) => void
  options: { value: T; label: React.ReactNode; icon?: React.ReactNode }[]
  className?: string
  'aria-label'?: string
  size?: 'default' | 'sm'
}) {
  const refs = React.useRef<(HTMLButtonElement | null)[]>([])
  const mark = React.useRef<HTMLSpanElement>(null)
  const at = options.findIndex((o) => o.value === value)
  const last = React.useRef<DOMRect | null>(null)
  // place the highlight on the chosen option (offsets: the options may wrap); from the old place, a FLIP glide
  React.useLayoutEffect(() => {
    const m = mark.current
    const place = () => {
      const b = refs.current[at]
      if (!m) return
      m.hidden = !b
      if (!b) return
      Object.assign(m.style, { left: `${b.offsetLeft}px`, top: `${b.offsetTop}px`, width: `${b.offsetWidth}px`, height: `${b.offsetHeight}px` })
      return m.getBoundingClientRect()
    }
    const r = place()
    const from = last.current
    last.current = r ?? null
    if (m && r && from && !reducedMotion() && r.width) {
      const dx = from.left - r.left
      const dy = from.top - r.top
      if (Math.abs(dx) > 1 || Math.abs(dy) > 1)
        m.animate([{ transform: `translate(${dx}px, ${dy}px) scaleX(${from.width / r.width})`, transformOrigin: 'left' }, { transform: 'none', transformOrigin: 'left' }], { duration: 240, easing: EASE_OUT })
    }
    const ro = new ResizeObserver(() => (last.current = place() ?? null))
    if (m?.parentElement) ro.observe(m.parentElement)
    return () => ro.disconnect()
  }, [at, options.length])
  return (
    <div role="radiogroup" aria-label={ariaLabel} className={cn('relative isolate inline-flex w-fit max-w-full flex-wrap items-center gap-0.5 rounded-lg bg-muted p-1', className)}>
      <span ref={mark} aria-hidden className="mx-lg-pill pointer-events-none absolute -z-10 rounded-md bg-background shadow-xs dark:bg-secondary" />
      {options.map((o, i) => {
        const active = o.value === value
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el
            }}
            type="button"
            role="radio"
            aria-checked={active}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => {
              const d = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
              if (!d) return
              e.preventDefault()
              const n = (i + d + options.length) % options.length
              onChange(options[n].value)
              refs.current[n]?.focus()
            }}
            className={cn(
              'inline-flex items-center justify-center gap-1.5 rounded-md px-3 font-medium whitespace-nowrap text-muted-foreground transition-colors outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-4',
              size === 'sm' ? 'h-7 text-[13px] max-md:h-10 pointer-coarse:h-10' : 'h-7 text-sm max-md:h-10 pointer-coarse:h-10',
              active && 'text-foreground',
            )}
          >
            {o.icon}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
