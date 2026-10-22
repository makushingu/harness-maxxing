import * as React from 'react'
import { ClipboardPaste, ExternalLink } from 'lucide-react'
import { mcpLoginCancel, mcpLoginFinish, mcpLoginStart } from '@/lib/queries'
import { errorMessage } from '@/lib/api'
import type { McpServer } from '@/lib/types'
import { useT } from '@/i18n'
import { Button, Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, Input, Spinner, toast } from '@/components/ui'
import { Callout } from '@/features/common'

// Outside ConnectDialog: a component defined during render would remount (and blur) the field on each key.
const Step = ({ n, title, children }: { n: number; title: React.ReactNode; children?: React.ReactNode }) => (
  <li className="grid grid-cols-[1.5rem_1fr] gap-x-3 gap-y-1.5">
    <span className="flex size-6 items-center justify-center rounded-full bg-primary/15 text-xs font-semibold text-primary">{n}</span>
    <span className="self-center text-sm font-medium">{title}</span>
    {children && <div className="col-start-2 grid gap-2 text-[13px] text-muted-foreground">{children}</div>}
  </li>
)

export function ConnectDialog({ server, onClose }: { server: McpServer | null; onClose: () => void }) {
  const t = useT()
  const [login, setLogin] = React.useState<{ login: string; url: string } | null>(null)
  const [error, setError] = React.useState<string | null>(null)
  const [redirect, setRedirect] = React.useState('')
  const [busy, setBusy] = React.useState(false)
  const current = React.useRef<string | null>(null)
  const alive = React.useRef(false)
  const start = React.useCallback((id: string) => {
    setLogin(null)
    setError(null)
    mcpLoginStart(id).then(
      (r) => {
        if (alive.current) {
          current.current = r.login
          setLogin(r)
        } else mcpLoginCancel(r.login).catch(() => {})
      },
      (e) => alive.current && setError(errorMessage(e)),
    )
  }, [])
  React.useEffect(() => {
    if (!server) return
    alive.current = true
    setRedirect('')
    start(server.id)
    return () => {
      alive.current = false
    }
  }, [server, start])
  const close = () => {
    if (current.current) mcpLoginCancel(current.current).catch(() => {})
    current.current = null
    onClose()
  }
  const finish = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!login) return
    setBusy(true)
    setError(null)
    try {
      await mcpLoginFinish(login.login, redirect.trim())
      current.current = null
      toast.success(t('mcp.connected', { name: server?.name || '' }))
      onClose()
    } catch (err) {
      setError(errorMessage(err))
      current.current = null
      setLogin(null)
    } finally {
      setBusy(false)
    }
  }
  // The service sends the browser back to Claude Code's local callback (redirect_uri): shown as is in the picture.
  const callback = React.useMemo(() => {
    try {
      return new URL(new URL(login?.url || '').searchParams.get('redirect_uri') || '').host || 'localhost'
    } catch {
      return 'localhost'
    }
  }, [login])
  const service = React.useMemo(() => {
    try {
      return new URL(login?.url || '').hostname.replace(/^www\./, '')
    } catch {
      return server?.name || ''
    }
  }, [login, server])
  const value = redirect.trim()
  const valid = /^https?:\/\/\S+$/.test(value) && /[?&](code|error)=/.test(value)
  const paste = async () => {
    try {
      setRedirect((await navigator.clipboard.readText()).trim())
    } catch {
      toast.error(t('mcp.pasteDenied'))
    }
  }
  return (
    <Dialog open={!!server} onOpenChange={(o) => !o && close()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('mcp.connectTitle', { name: server?.name || '' })}</DialogTitle>
          <DialogDescription>{t('mcp.connectDesc')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={finish} className="grid gap-4" noValidate>
          <ol className="grid gap-4">
            <Step n={1} title={t('mcp.step1')}>
              {login ? (
                <Button asChild variant="outline" className="w-fit">
                  <a href={login.url} target="_blank" rel="noreferrer">
                    <ExternalLink /> {t('mcp.openLogin')}
                  </a>
                </Button>
              ) : error ? null : (
                <span className="flex items-center gap-2">
                  <Spinner /> {t('mcp.preparing')}
                </span>
              )}
            </Step>
            <Step n={2} title={t('mcp.step2', { service })} />
            <Step n={3} title={t('mcp.step3')}>
              <span>{t('mcp.step3Desc')}</span>
              {/* What the browser shows: an error page whose address holds the code. */}
              <div className="overflow-hidden rounded-lg border bg-muted/30 text-xs">
                <div className="flex items-center gap-2 border-b bg-muted/60 px-2.5 py-1.5">
                  <span className="flex gap-1">
                    <span className="size-2 rounded-full bg-muted-foreground/30" />
                    <span className="size-2 rounded-full bg-muted-foreground/30" />
                    <span className="size-2 rounded-full bg-muted-foreground/30" />
                  </span>
                  <span className="min-w-0 flex-1 truncate rounded bg-background px-2 py-0.5 font-mono ring-2 ring-primary/60">
                    http://{callback}/callback?<b className="text-primary">code=</b>…&amp;state=…
                  </span>
                </div>
                <div className="px-3 py-2.5 text-muted-foreground">{t('mcp.browserError')}</div>
              </div>
              <span>{t('mcp.step3Copy')}</span>
            </Step>
            <Step n={4} title={t('mcp.step4')}>
              <div className="flex gap-1.5">
                <Input value={redirect} onChange={(e) => setRedirect(e.target.value)} placeholder={`http://${callback}/callback?code=…`} className="flex-1 font-mono text-xs" autoComplete="off" spellCheck={false} disabled={!login} aria-label={t('mcp.step4')} />
                {'clipboard' in navigator && 'readText' in navigator.clipboard && (
                  <Button variant="outline" onClick={paste} disabled={!login}>
                    <ClipboardPaste /> {t('mcp.paste')}
                  </Button>
                )}
              </div>
              {value && !valid && <span className="text-xs text-warning">{t('mcp.noCode')}</span>}
            </Step>
          </ol>
          <details className="rounded-lg border px-3 py-2 text-[13px] text-muted-foreground">
            <summary className="cursor-pointer font-medium text-foreground">{t('mcp.whyTitle')}</summary>
            <p className="mt-1.5">{t('mcp.whyBody')}</p>
          </details>
          {error && <Callout tone="error">{error}</Callout>}
          <DialogFooter>
            <Button variant="outline" onClick={close}>
              {t('common.cancel')}
            </Button>
            {!login && error && server ? (
              <Button onClick={() => start(server.id)}>{t('mcp.retry')}</Button>
            ) : (
              <Button type="submit" loading={busy} disabled={!login || !valid}>
                {t('mcp.finish')}
              </Button>
            )}
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
