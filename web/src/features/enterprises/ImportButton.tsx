// "Import": picks an exported enterprise zip and creates a new enterprise from it (positions vacant, no project linked).
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Upload } from 'lucide-react'
import { useT } from '@/i18n'
import { enterpriseRoute, useImportEnterprise } from '@/lib/queries'
import { Button, toast } from '@/components/ui'

export function ImportButton({ size }: { size?: 'sm' }) {
  const t = useT()
  const nav = useNavigate()
  const imp = useImportEnterprise()
  const input = React.useRef<HTMLInputElement>(null)
  const pick = (f: File | undefined) => {
    if (!f) return
    imp.mutate(f, {
      onSuccess: (e) => {
        toast.success(e.skipped?.length ? t('ent.import.doneSkipped', { n: e.skipped.length }) : t('ent.import.done'))
        nav(enterpriseRoute(e.id))
      },
    })
  }
  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        data-testid="enterprise-import-file"
        onChange={(ev) => {
          pick(ev.target.files?.[0])
          ev.target.value = ''
        }}
      />
      <Button variant="outline" size={size} loading={imp.isPending} onClick={() => input.current?.click()} data-testid="enterprise-import">
        <Upload /> {t('ent.import.action')}
      </Button>
    </>
  )
}
