import * as React from 'react'
import { Eye, EyeOff } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Input } from './input'
import { Textarea } from './textarea'

type Props = React.ComponentProps<'input'> & {
  /** Multi-line values allowed (PEM, SSH keys): a paste with line breaks switches to a masked text area. An input
   * drops the line breaks of its value, so the key would be stored on one line. */
  onValueChange?: (value: string) => void
}

/** Password/token input with a show/hide toggle. Never autofilled by password managers unless `autoComplete` says so. */
export function SecretInput({ className, autoComplete = 'off', onValueChange, ...props }: Props) {
  const t = useT()
  const [show, setShow] = React.useState(false)
  const multi = !!onValueChange && typeof props.value === 'string' && props.value.includes('\n')
  // The field changes element when the value gets or loses its line breaks: keep the focus in it.
  const area = React.useRef<HTMLTextAreaElement>(null)
  const line = React.useRef<HTMLInputElement>(null)
  const switched = React.useRef(false)
  React.useLayoutEffect(() => {
    if (!switched.current) return
    switched.current = false
    const el = multi ? area.current : line.current
    el?.focus()
    if (el) el.selectionStart = el.selectionEnd = el.value.length
  }, [multi])
  const onPaste = (e: React.ClipboardEvent<HTMLInputElement>) => {
    const text = e.clipboardData.getData('text').replace(/\r\n?/g, '\n')
    if (!onValueChange || !text.includes('\n')) return
    e.preventDefault()
    const el = e.currentTarget
    switched.current = true
    onValueChange(el.value.slice(0, el.selectionStart ?? el.value.length) + text + el.value.slice(el.selectionEnd ?? el.value.length))
  }
  return (
    <div className={cn('relative', className)}>
      {multi ? (
        <Textarea
          ref={area}
          value={props.value as string}
          onChange={(e) => {
            if (!e.target.value.includes('\n')) switched.current = true
            onValueChange!(e.target.value)
          }}
          placeholder={props.placeholder}
          disabled={props.disabled}
          autoComplete={autoComplete}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          minRows={3}
          maxRows={8}
          className={cn('pr-10 font-mono text-xs', !show && '[-webkit-text-security:disc]')}
        />
      ) : (
        <Input
          ref={line}
          {...props}
          onChange={props.onChange ?? (onValueChange && ((e) => onValueChange(e.target.value)))}
          onPaste={onPaste}
          type={show ? 'text' : 'password'}
          autoComplete={autoComplete}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          className="pr-10 font-mono"
        />
      )}
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        aria-label={show ? t('common.hide') : t('common.show')}
        aria-pressed={show}
        className={cn(
          'absolute right-0 flex w-10 pointer-coarse:w-11 items-center justify-center rounded-r-md text-muted-foreground hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none',
          multi ? 'top-0 h-9' : 'inset-y-0',
        )}
      >
        {show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  )
}
