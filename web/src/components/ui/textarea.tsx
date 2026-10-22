import * as React from 'react'
import { cn } from '@/lib/utils'
import { inputBase } from './input'

type Props = React.ComponentProps<'textarea'> & {
  /** Grow with content between minRows and maxRows (default true). */
  autosize?: boolean
  minRows?: number
  maxRows?: number
}

export function Textarea({ className, autosize = true, minRows = 3, maxRows = 16, onChange, style, ref, ...props }: Props) {
  const inner = React.useRef<HTMLTextAreaElement | null>(null)
  const setRef = (el: HTMLTextAreaElement | null) => {
    inner.current = el
    if (typeof ref === 'function') ref(el)
    else if (ref) (ref as React.RefObject<HTMLTextAreaElement | null>).current = el
  }
  const resize = React.useCallback(() => {
    const el = inner.current
    if (!el || !autosize) return
    const cs = getComputedStyle(el)
    const line = parseFloat(cs.lineHeight) || 20
    const pad = parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom) + parseFloat(cs.borderTopWidth) + parseFloat(cs.borderBottomWidth)
    el.style.height = 'auto'
    const h = Math.min(Math.max(el.scrollHeight, minRows * line + pad), maxRows * line + pad)
    el.style.height = `${h}px`
    el.style.overflowY = el.scrollHeight > h ? 'auto' : 'hidden'
  }, [autosize, minRows, maxRows])
  React.useLayoutEffect(resize, [resize, props.value])
  return (
    <textarea
      ref={setRef}
      rows={minRows}
      className={cn(inputBase, 'block resize-none py-2 leading-relaxed', className)}
      style={style}
      onChange={(e) => {
        onChange?.(e)
        // controlled: the layout effect on `value` resizes once - not here a second time (5 layouts per key)
        if (props.value === undefined) resize()
      }}
      {...props}
    />
  )
}
