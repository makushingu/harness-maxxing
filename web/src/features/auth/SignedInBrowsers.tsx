import { useDisconnectBrowser, useDisconnectOthers, useSignedInBrowsers } from '@/lib/queries'
import { fmtRelative } from '@/lib/format'
import { useLang, useT } from '@/i18n'
import { Badge, Button, Sensitive, Skeleton, toast } from '@/components/ui'

/** The browsers signed in: one line each, Disconnect, and "Disconnect all the others". */
export function SignedInBrowsers() {
  const t = useT()
  const lang = useLang()
  const { data } = useSignedInBrowsers()
  const drop = useDisconnectBrowser()
  const others = useDisconnectOthers()
  if (!data) return <Skeleton className="h-16 w-full" />
  const alone = data.devices.filter((d) => !d.current).length === 0 && !(data.legacy && !data.legacy_current)
  return (
    <div className="grid gap-4">
      <ul className="divide-y rounded-lg border">
        {data.devices.map((d) => (
          <li key={d.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
            <div className="grid min-w-0 gap-0.5">
              <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
                <span className="[overflow-wrap:anywhere]">{d.label}</span>
                {d.current && <Badge variant="secondary">{t('security.brThis')}</Badge>}
              </span>
              <span className="text-[13px] text-muted-foreground">
                {t('security.brSeen', { when: fmtRelative(d.seen, lang) })}
                {d.ip && (
                  <>
                    {' · '}
                    <Sensitive>{d.ip}</Sensitive>
                  </>
                )}
              </span>
            </div>
            {!d.current && (
              <Button variant="outline" size="sm" loading={drop.isPending && drop.variables === d.id} onClick={() => drop.mutate(d.id)}>
                {t('security.brDisconnect')}
              </Button>
            )}
          </li>
        ))}
        {data.legacy && (
          <li className="grid gap-0.5 px-4 py-3">
            <span className="flex flex-wrap items-center gap-2 text-sm font-medium">
              {t('security.brLegacy')}
              {data.legacy_current && <Badge variant="secondary">{t('security.brThis')}</Badge>}
            </span>
            <span className="text-[13px] text-muted-foreground">{t('security.brLegacyDesc')}</span>
          </li>
        )}
      </ul>
      <div>
        <Button variant="outline" disabled={alone} loading={others.isPending} onClick={() => others.mutate(undefined, { onSuccess: () => toast.success(t('security.brOthersDone')) })}>
          {t('security.brOthers')}
        </Button>
      </div>
    </div>
  )
}
