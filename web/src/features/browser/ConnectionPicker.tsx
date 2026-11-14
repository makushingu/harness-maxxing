// A profile's connection (its exit: the server's IP, a phone, a box, a proxy): pick another, or add one; the eye shows
// the address the sites see through it (its last test). The connection belongs to the profile: every navigator on it
// (the person's, its agents', its sessions') goes out there.
import { useNavigate } from 'react-router'
import { Eye } from 'lucide-react'
import { useT } from '@/i18n'
import { useBrowserStatus, useSaveBrowserProfile } from '@/lib/queries'
import { cn } from '@/lib/utils'
import { Button, Popover, PopoverContent, PopoverTrigger, Select } from '@/components/ui'
import { exitLine, exitTone, testWhere } from './profiles'

export function ConnectionPicker({ pid, className, note, wide }: { pid: string; className?: string; note?: boolean; wide?: boolean }) {
  const t = useT()
  const go = useNavigate()
  const { data: st } = useBrowserStatus()
  const save = useSaveBrowserProfile()
  const p = st?.profiles.find((x) => x.id === pid)
  if (!st || !p) return null
  const e = st.exits.find((x) => x.id === p.exit)
  const test = p.exit === 'direct' ? st.direct.test : e?.test
  const checking = p.exit === 'direct' ? st.direct.checking : e?.checking
  const options = [
    { value: 'direct', label: <Option tone="bg-success" name={t('browser.exit.direct')} line={testWhere(st.direct.test)} /> },
    ...st.exits.map((x) => ({ value: x.id, label: <Option tone={exitTone(x)} name={x.name} line={exitLine(x, t)} /> })),
    { value: '__new', label: <span className="text-primary">+ {t('browser.exit.add')}</span> },
  ]
  return (
    <span className={cn('inline-flex min-w-0 items-center gap-1', className)} data-testid="browser-connection">
      {!wide && <span className="hidden text-[12px] text-muted-foreground sm:inline">{t('browser.connection')}</span>}
      <Select
        className={wide ? 'h-9 min-w-0 flex-1 text-[13px]' : 'h-8 w-52 max-w-[50vw] text-[13px]'}
        aria-label={t('browser.connection')}
        value={p.exit}
        onValueChange={(x) => (x === '__new' ? go('/settings/browser?exit=new') : x !== p.exit && save.mutate({ id: pid, exit: x }))}
        options={options}
      />
      <Popover>
        <PopoverTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t('browser.connection.seen', { ip: '' })} data-testid="browser-connection-ip">
            <Eye />
          </Button>
        </PopoverTrigger>
        <PopoverContent align="end" className="grid w-72 gap-1.5 text-[13px]">
          {test?.ok ? (
            <>
              <span className="font-medium">{t('browser.connection.seen', { ip: test.ip || '?' })}</span>
              <span className="text-muted-foreground">{[testWhere(test), test.city].filter(Boolean).join(' · ')}</span>
            </>
          ) : (
            <span className="text-muted-foreground">{t(checking ? 'browser.connection.checking' : 'browser.connection.untested')}</span>
          )}
          {note && <span className="border-t pt-1.5 text-[12px] text-muted-foreground">{t('browser.connection.shared')}</span>}
          <button type="button" className="justify-self-start text-[12px] text-primary hover:underline" onClick={() => go(`/settings/browser?exit=${encodeURIComponent(p.exit)}`)}>
            {t('browser.down.open')}
          </button>
        </PopoverContent>
      </Popover>
    </span>
  )
}

function Option({ tone, name, line }: { tone: string; name: string; line: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-2">
      <span className={cn('size-1.5 shrink-0 rounded-full', tone)} />
      <span className="truncate">{name}</span>
      {line && <span className="truncate text-muted-foreground">· {line}</span>}
    </span>
  )
}
