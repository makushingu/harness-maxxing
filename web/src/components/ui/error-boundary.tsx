// A render error stays where it happened: one widget, one message, the file viewer, the HUD - not the whole app.
// `variant`: "inline" (a small line in place of the part), "card" (a widget), "page" (the root, outside the router).
import * as React from 'react'
import { RefreshCw, TriangleAlert } from 'lucide-react'
import { useT } from '@/i18n'
import { cn } from '@/lib/utils'

type Props = { children: React.ReactNode; variant?: 'inline' | 'card' | 'page'; className?: string; resetKey?: unknown }
type State = { error: Error | null; key: unknown }

/** A chunk of a previous build is gone (the server was updated while the tab stayed open): a reload fixes it. */
export const isChunkError = (e: unknown) => e instanceof Error && /dynamically imported module|Importing a module script failed|Failed to fetch dynamically|Unable to preload/i.test(e.message)

export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null, key: this.props.resetKey }

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error }
  }

  // New data for the same part (resetKey changed): try again.
  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error('render error', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return <Fallback error={this.state.error} variant={this.props.variant ?? 'inline'} className={this.props.className} onRetry={() => this.setState({ error: null })} />
  }
}

function Fallback({ error, variant, className, onRetry }: { error: Error; variant: 'inline' | 'card' | 'page'; className?: string; onRetry: () => void }) {
  const t = useT()
  const chunk = isChunkError(error)
  const action = chunk || variant === 'page' ? () => window.location.reload() : onRetry
  const label = chunk || variant === 'page' ? t('error.reload') : t('common.retry')
  if (variant === 'page')
    return (
      <div role="alert" className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
        <TriangleAlert className="size-8 text-destructive" />
        <p className="text-base font-medium">{chunk ? t('error.updated') : t('error.title')}</p>
        <p className="max-w-md text-sm text-muted-foreground">{chunk ? t('error.updatedDesc') : error.message}</p>
        <button type="button" onClick={action} className="inline-flex h-9 items-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground">
          <RefreshCw className="size-4" /> {label}
        </button>
      </div>
    )
  return (
    <div role="alert" data-testid="part-error" className={cn('flex min-w-0 items-center gap-2 text-xs text-muted-foreground', variant === 'card' ? 'p-[var(--pad-card)]' : 'rounded-md border border-dashed px-2.5 py-1.5', className)}>
      <TriangleAlert className="size-3.5 shrink-0 text-destructive" />
      <span className="min-w-0 flex-1 truncate" title={error.message}>
        {chunk ? t('error.updated') : t('error.part')}
      </span>
      <button type="button" onClick={action} className="shrink-0 rounded px-1.5 py-0.5 font-medium text-foreground hover:bg-accent">
        {label}
      </button>
    </div>
  )
}
