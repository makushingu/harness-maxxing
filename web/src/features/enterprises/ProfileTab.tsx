// Tab "Profile": the enterprise mission (its CLAUDE.md, what every occupant reads first) and the structured company
// profile (products, hours, terms, contact, FAQ): what customers may hear, so nothing private belongs here.
import * as React from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { useT } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { useEnterpriseAbout, useEnterpriseInsights, useEnterpriseProfile, usePutEnterpriseAbout, usePutEnterpriseProfile } from '@/lib/queries'
import type { Enterprise, EnterpriseProfile } from '@/lib/types'
import { cn } from '@/lib/utils'
import { Button, EmptyState, FormField, Input, Skeleton, Textarea, toast } from '@/components/ui'
import { SectionStack, SettingsCard } from '@/pages/settings/sections/ui'

export function ProfileTab({ enterprise: e }: { enterprise: Enterprise }) {
  return (
    <div data-testid="enterprise-profile">
      <SectionStack>
        <Mission id={e.id} />
        <CompanyProfile id={e.id} />
      </SectionStack>
    </div>
  )
}

function Mission({ id }: { id: string }) {
  const t = useT()
  const { data, isLoading, error, refetch } = useEnterpriseAbout(id)
  const put = usePutEnterpriseAbout()
  const [text, setText] = React.useState<string | null>(null)
  const value = text ?? data?.text ?? ''
  const dirty = data != null && value !== data.text
  const noteMax = data?.note_max || 3000
  const max = data?.max || 20000
  const over = value.length > noteMax
  return (
    <SettingsCard title={t('ent.profile.mission')} description={t('ent.profile.missionDesc')}>
      {isLoading ? (
        <Skeleton className="h-40" />
      ) : error || !data ? (
        <EmptyState
          tone="error"
          compact
          title={t('ent.profile.loadError')}
          description={errorMessage(error)}
          action={
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      ) : (
        <form
          className="grid gap-3"
          onSubmit={(ev) => {
            ev.preventDefault()
            put.mutate({ id, text: value }, { onSuccess: () => setText(null), onError: (err) => toast.error(errorMessage(err)) })
          }}
        >
          <FormField label={t('ent.profile.missionLabel')} hint={over ? t('ent.profile.missionOver', { count: noteMax }) : t('ent.profile.missionHint')}>
            <Textarea value={value} onChange={(ev) => setText(ev.target.value)} minRows={8} maxRows={24} maxLength={max} placeholder={t('ent.profile.missionPh')} data-testid="mission-text" />
          </FormField>
          <div className="flex items-center gap-3">
            <Button type="submit" size="sm" disabled={!dirty} loading={put.isPending} data-testid="mission-save">
              {t('common.save')}
            </Button>
            <span className={cn('text-xs text-muted-foreground tabular-nums', over && 'text-warning')} data-testid="mission-counter">
              {t('ent.profile.counter', { count: value.length, max: noteMax })}
            </span>
          </div>
        </form>
      )}
    </SettingsCard>
  )
}

type Row = { key: string; value: string }
type Draft = {
  products: { name: string; price: string; url: string; src: Record<string, unknown> }[]
  hours: string
  terms: Row[]
  contactText: string
  contactRows: Row[] | null
  faq: { q: string; a: string; src: Record<string, unknown> }[]
}

const str = (v: unknown) => (v == null ? '' : String(v))
const rowsOf = (o: Record<string, unknown>): Row[] => Object.entries(o).map(([key, value]) => ({ key, value: str(value) }))
/** Rows back to an object: a value that was a number or a boolean stays one when it still reads as one. */
const objOf = (rows: Row[], was: Record<string, unknown>) => {
  const out: Record<string, string | number | boolean> = {}
  for (const r of rows) {
    const k = r.key.trim()
    if (!k) continue
    const v = r.value.trim()
    const old = was[k]
    out[k] = typeof old === 'number' && v !== '' && Number.isFinite(Number(v)) ? Number(v) : typeof old === 'boolean' && (v === 'true' || v === 'false') ? v === 'true' : v
  }
  return out
}

function draftOf(p: EnterpriseProfile): Draft {
  const contact = p.contact
  return {
    products: (p.products || []).map((x) => ({ name: str(x.name), price: str(x.price), url: str(x.url), src: x })),
    hours: str(p.hours),
    terms: rowsOf(p.terms || {}),
    contactText: typeof contact === 'string' ? contact : '',
    contactRows: contact && typeof contact === 'object' ? rowsOf(contact) : null,
    faq: (p.faq || []).map((x) => ({ q: str(x.q), a: str(x.a), src: x })),
  }
}

function profileOf(d: Draft, was: EnterpriseProfile): EnterpriseProfile {
  return {
    ...was,
    products: d.products.filter((x) => x.name.trim()).map((x) => ({ ...x.src, name: x.name.trim(), price: x.price.trim(), url: x.url.trim() })),
    hours: d.hours.trim(),
    terms: objOf(d.terms, was.terms || {}),
    contact: d.contactRows ? objOf(d.contactRows, (typeof was.contact === 'object' && was.contact) || {}) : d.contactText.trim(),
    faq: d.faq.filter((x) => x.q.trim() && x.a.trim()).map((x) => ({ ...x.src, q: x.q.trim(), a: x.a.trim() })),
  }
}

function CompanyProfile({ id }: { id: string }) {
  const t = useT()
  const { data, isLoading, error, refetch } = useEnterpriseProfile(id)
  const put = usePutEnterpriseProfile()
  const [draft, setDraft] = React.useState<Draft | null>(null)
  // a fresh server copy (saved here, or changed elsewhere while nothing is being edited) restarts the form
  const [seen, setSeen] = React.useState<EnterpriseProfile | undefined>()
  if (data && data !== seen) {
    setSeen(data)
    setDraft(draftOf(data))
  }
  if (isLoading || (data && !draft)) return <SettingsCard title={t('ent.profile.company')}><Skeleton className="h-40" /></SettingsCard>
  if (error || !data || !draft)
    return (
      <SettingsCard title={t('ent.profile.company')}>
        <EmptyState
          tone="error"
          compact
          title={t('ent.profile.loadError')}
          description={errorMessage(error)}
          action={
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              {t('common.retry')}
            </Button>
          }
        />
      </SettingsCard>
    )
  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })
  const dirty = JSON.stringify(profileOf(draft, data)) !== JSON.stringify(profileOf(draftOf(data), data))
  const save = () =>
    put.mutate(
      { id, profile: profileOf(draft, data) },
      {
        onSuccess: (r) => toast.success(t(r.request ? 'ent.profile.waiting' : 'ent.profile.saved')),
        onError: (err) => toast.error(errorMessage(err)),
      },
    )
  return (
    <SettingsCard
      title={t('ent.profile.company')}
      description={t('ent.profile.companyDesc')}
      actions={
        <Button size="sm" onClick={save} disabled={!dirty} loading={put.isPending} data-testid="profile-save">
          {t('common.save')}
        </Button>
      }
    >
      <div className="grid gap-8">
        <section className="grid gap-3" aria-label={t('ent.profile.products')}>
          <h4 className="text-sm font-medium">{t('ent.profile.products')}</h4>
          {draft.products.length > 0 && (
            <div className="grid gap-2" data-testid="profile-products">
              {draft.products.map((p, i) => (
                <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_minmax(0,2fr)_auto]">
                  <Input value={p.name} onChange={(ev) => set({ products: draft.products.map((x, j) => (j === i ? { ...x, name: ev.target.value } : x)) })} placeholder={t('ent.profile.productName')} aria-label={t('ent.profile.productName')} maxLength={120} className="max-sm:col-span-1" />
                  <Input value={p.price} onChange={(ev) => set({ products: draft.products.map((x, j) => (j === i ? { ...x, price: ev.target.value } : x)) })} placeholder={t('ent.profile.productPrice')} aria-label={t('ent.profile.productPrice')} maxLength={60} className="max-sm:order-3" />
                  <Input value={p.url} onChange={(ev) => set({ products: draft.products.map((x, j) => (j === i ? { ...x, url: ev.target.value } : x)) })} placeholder={t('ent.profile.productUrl')} aria-label={t('ent.profile.productUrl')} maxLength={300} className="max-sm:order-4 max-sm:col-span-2" />
                  <Button type="button" variant="ghost" size="icon-sm" aria-label={t('ent.profile.removeRow')} onClick={() => set({ products: draft.products.filter((_, j) => j !== i) })} className="max-sm:order-2">
                    <Trash2 />
                  </Button>
                </div>
              ))}
            </div>
          )}
          <div>
            <Button type="button" variant="outline" size="sm" onClick={() => set({ products: [...draft.products, { name: '', price: '', url: '', src: {} }] })} data-testid="profile-product-add">
              <Plus /> {t('ent.profile.addProduct')}
            </Button>
          </div>
        </section>

        <FormField label={t('ent.profile.hours')} hint={t('ent.profile.hoursHint')}>
          <Input value={draft.hours} onChange={(ev) => set({ hours: ev.target.value })} maxLength={1000} autoComplete="off" />
        </FormField>

        <RowsEditor title={t('ent.profile.terms')} hint={t('ent.profile.termsHint')} rows={draft.terms} onChange={(terms) => set({ terms })} testid="profile-terms" />

        {draft.contactRows ? (
          <RowsEditor title={t('ent.profile.contact')} hint={t('ent.profile.contactHint')} rows={draft.contactRows} onChange={(contactRows) => set({ contactRows })} testid="profile-contact" />
        ) : (
          <FormField label={t('ent.profile.contact')} hint={t('ent.profile.contactHint')}>
            <Textarea value={draft.contactText} onChange={(ev) => set({ contactText: ev.target.value })} minRows={2} maxRows={8} maxLength={1000} />
          </FormField>
        )}

        <section className="grid gap-3" aria-label={t('ent.profile.faq')}>
          <h4 className="text-sm font-medium">{t('ent.profile.faq')}</h4>
          {draft.faq.map((f, i) => (
            <div key={i} className="grid gap-2 rounded-lg border p-3" data-testid="profile-faq-item">
              <Input value={f.q} onChange={(ev) => set({ faq: draft.faq.map((x, j) => (j === i ? { ...x, q: ev.target.value } : x)) })} placeholder={t('ent.profile.question')} aria-label={t('ent.profile.question')} maxLength={300} />
              <Textarea value={f.a} onChange={(ev) => set({ faq: draft.faq.map((x, j) => (j === i ? { ...x, a: ev.target.value } : x)) })} placeholder={t('ent.profile.answer')} aria-label={t('ent.profile.answer')} minRows={2} maxRows={8} maxLength={2000} />
              <div>
                <Button type="button" variant="ghost" size="sm" onClick={() => set({ faq: draft.faq.filter((_, j) => j !== i) })}>
                  <Trash2 /> {t('ent.profile.removeRow')}
                </Button>
              </div>
            </div>
          ))}
          <div>
            <Button type="button" variant="outline" size="sm" onClick={() => set({ faq: [...draft.faq, { q: '', a: '', src: {} }] })} data-testid="profile-faq-add">
              <Plus /> {t('ent.profile.addFaq')}
            </Button>
          </div>
        </section>
        <Suggestions id={id} />
      </div>
    </SettingsCard>
  )
}

/** Key / value rows (terms, contact points). */
function RowsEditor({ title, hint, rows, onChange, testid }: { title: string; hint: string; rows: Row[]; onChange: (r: Row[]) => void; testid: string }) {
  const t = useT()
  return (
    <section className="grid gap-3" aria-label={title} data-testid={testid}>
      <div className="grid gap-1">
        <h4 className="text-sm font-medium">{title}</h4>
        <p className="text-[13px] text-muted-foreground">{hint}</p>
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,2fr)_auto]">
          <Input value={r.key} onChange={(ev) => onChange(rows.map((x, j) => (j === i ? { ...x, key: ev.target.value } : x)))} placeholder={t('ent.profile.key')} aria-label={t('ent.profile.key')} maxLength={80} autoComplete="off" />
          <Input value={r.value} onChange={(ev) => onChange(rows.map((x, j) => (j === i ? { ...x, value: ev.target.value } : x)))} placeholder={t('ent.profile.value')} aria-label={t('ent.profile.value')} maxLength={1000} autoComplete="off" className="max-sm:order-3 max-sm:col-span-2" />
          <Button type="button" variant="ghost" size="icon-sm" aria-label={t('ent.profile.removeRow')} onClick={() => onChange(rows.filter((_, j) => j !== i))} className="max-sm:order-2">
            <Trash2 />
          </Button>
        </div>
      ))}
      <div>
        <Button type="button" variant="outline" size="sm" onClick={() => onChange([...rows, { key: '', value: '' }])}>
          <Plus /> {t('ent.profile.addRow')}
        </Button>
      </div>
    </section>
  )
}

/** What customers could not get answered this week (the insights loop, when the server has one); nothing when it has not. */
function Suggestions({ id }: { id: string }) {
  const t = useT()
  const { data } = useEnterpriseInsights(id)
  const list = (data?.unanswered || []).map((x) => (typeof x === 'string' ? x : typeof x === 'object' && x && 'q' in x ? str((x as { q: unknown }).q) : typeof x === 'object' && x && 'text' in x ? str((x as { text: unknown }).text) : '')).filter(Boolean)
  if (list.length === 0) return null
  return (
    <section className="grid gap-2" aria-label={t('ent.profile.unanswered')} data-testid="profile-unanswered">
      <h4 className="text-sm font-medium">{t('ent.profile.unanswered')}</h4>
      <p className="text-[13px] text-muted-foreground">{t('ent.profile.unansweredDesc')}</p>
      <ul className="list-disc pl-5 text-[13px]">
        {list.map((q, i) => (
          <li key={i}>{q}</li>
        ))}
      </ul>
    </section>
  )
}
