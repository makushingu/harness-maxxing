import * as React from 'react'
import { LogIn } from 'lucide-react'
import { useMcp } from '@/lib/queries'
import { useT } from '@/i18n'
import { Button } from '@/components/ui'
import { ConnectDialog } from './ConnectDialog'

// Claude Code names the tools of a server mcp__<server>__<tool>, with every character outside [A-Za-z0-9_-] turned into "_".
const norm = (s: string) => s.replace(/[^A-Za-z0-9_-]/g, '_')

/** The server an `mcp__<server>__authenticate` tool call is about ("<server>" of the tool name), or null. */
export function authServerOf(tool: string): string | null {
  const m = /^mcp__(.+)__(?:authenticate|complete_authentication)$/.exec(tool)
  return m ? m[1] : null
}

/** In the chat: the agent asked to sign in to an MCP server -> one button opens the connection steps right here. */
export function McpAuthButton({ server }: { server: string }) {
  const t = useT()
  const { data } = useMcp()
  const [open, setOpen] = React.useState(false)
  const found = (data?.servers || []).filter((s) => (s.type === 'http' || s.type === 'sse') && norm(s.name) === server)
  const target = found.find((s) => s.state === 'needs_auth') || found[0]
  if (!target) return null
  return (
    <div className="flex flex-wrap items-center gap-2 border-t bg-background/40 px-2.5 py-2">
      {/* the button stays when the last check said "connected": the agent asks because its sign-in expired since */}
      <Button size="sm" variant={target.state === 'connected' ? 'outline' : undefined} onClick={() => setOpen(true)}>
        <LogIn /> {t('mcp.connectTitle', { name: target.name })}
      </Button>
      <span className="text-xs text-muted-foreground">
        {target.state === 'connected' ? t('mcp.chatConnected', { name: target.name }) : t('mcp.chatHint')}
      </span>
      <ConnectDialog server={open ? target : null} onClose={() => setOpen(false)} />
    </div>
  )
}
