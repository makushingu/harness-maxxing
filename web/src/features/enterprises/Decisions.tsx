// Tab "Decisions": the enterprise's decision log, newest first, filtered by kind and position. Read-only.
import * as React from 'react'
import { ScrollText } from 'lucide-react'
import { useLang, useT, type TKey } from '@/i18n'
import { errorMessage } from '@/lib/api'
import { useEnterpriseDecisions } from '@/lib/queries'
import { fmtDate, fmtRelative } from '@/lib/format'
import type { DecisionItem, Enterprise } from '@/lib/types'
import { Badge, Button, EmptyState, Select, Sensitive, Skeleton } from '@/components/ui'

const ALL = '__all'

const KIND_LABEL: Record<string, TKey> = {
  accept: 'ent.kind.accept',
  answer: 'ent.kind.answer',
  assign: 'ent.kind.assign',
  block: 'ent.kind.block',
  climb: 'ent.kind.climb',
  delivery: 'ent.kind.delivery',
  escalation: 'ent.kind.escalation',
  grant_expired: 'ent.kind.grant_expired',
  handin: 'ent.kind.handin',
  note: 'ent.kind.note',
  objective: 'ent.kind.objective',
  profile: 'ent.kind.profile',
  request: 'ent.kind.request',
  request_allowed: 'ent.kind.request_allowed',
  request_climbed: 'ent.kind.request_climbed',
  request_skipped: 'ent.kind.request_skipped',
  run: 'ent.kind.run',
  skip: 'ent.kind.skip',
  structure: 'ent.kind.structure',
  wait: 'ent.kind.wait',
}

export function Decisions({ enterprise: e }: { enterprise: Enterprise }) {
  const t = useT()
  const [kind, setKind] = React.useState(ALL)
  const [pos, setPos] = React.useState(ALL)
  const kinds = [{ value: ALL, label: t('ent.decisions.allKinds') }, ...Object.entries(KIND_LABEL).map(([value, key]) => ({ value, label: t(key) }))]
  const positions = [{ value: ALL, label: t('ent.decisions.allPositions') }, ...e.positions.map((p) => ({ value: p.id, label: p.title }))]
  return (
    <div className="grid gap-4" data-testid="enterprise-decisions">
      <div className="grid gap-3 sm:grid-cols-2 lg:max-w-xl">
        <Select value={kind} onValueChange={setKind} options={kinds} aria-label={t('ent.decisions.kind')} />
        <Select value={pos} onValueChange={setPos} options={positions} aria-label={t('ent.decisions.position')} />
      </div>
      <DecisionPage enterprise={e} before={null} kind={kind === ALL ? '' : kind} position={pos === ALL ? '' : pos} first />
    </div>
  )
}

/** One page of the log; its "Load more" mounts the next page under it. The filters narrow what each page shows. */
function DecisionPage({ enterprise: e, before, kind, position, first }: { enterprise: Enterprise; before: number | null; kind: string; position: string; first?: boolean }) {
  const t = useT()
  const [more, setMore] = React.useState(false)
  const { data, isLoading, error, refetch } = useEnterpriseDecisions(e.id, before)
  if (isLoading) return <Skeleton className="h-40 rounded-xl" />
  if (error || !data)
    return (
      <EmptyState
        tone="error"
        icon={ScrollText}
        title={t('ent.decisions.loadError')}
        description={errorMessage(error)}
        action={
          <Button variant="outline" onClick={() => void refetch()}>
            {t('common.retry')}
          </Button>
        }
      />
    )
  const items = data.items.filter((i) => (!kind || i.kind === kind) && (!position || i.position === position || i.by === position))
  return (
    <>
      {items.length === 0 ? (
        first && <EmptyState icon={ScrollText} title={t('ent.decisions.empty')} description={t(data.next != null ? 'ent.decisions.emptyFiltered' : 'ent.decisions.emptyDesc')} compact />
      ) : (
        <ul className="divide-y rounded-xl border bg-card" data-testid="decision-list">
          {items.map((i, n) => (
            <DecisionRow key={`${i.at}-${n}`} enterprise={e} item={i} />
          ))}
        </ul>
      )}
      {data.next != null &&
        (more ? (
          <DecisionPage enterprise={e} before={data.next} kind={kind} position={position} />
        ) : (
          <div>
            <Button variant="outline" size="sm" onClick={() => setMore(true)} data-testid="decisions-more">
              {t('ent.decisions.more')}
            </Button>
          </div>
        ))}
    </>
  )
}

function DecisionRow({ enterprise: e, item: i }: { enterprise: Enterprise; item: DecisionItem }) {
  const t = useT()
  const lang = useLang()
  const title = (id: string) => (id === 'owner' ? t('ent.decisions.owner') : e.positions.find((p) => p.id === id)?.title || id)
  return (
    <li className="grid gap-1 px-4 py-3 text-sm" data-testid="decision-row">
      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
        <Badge variant="muted">{KIND_LABEL[i.kind] ? t(KIND_LABEL[i.kind]) : i.kind}</Badge>
        <span>
          <Sensitive length={10}>{title(i.by)}</Sensitive>
        </span>
        {i.position && i.position !== i.by && (
          <span>
            {'→ '}
            <Sensitive length={10}>{title(i.position)}</Sensitive>
          </span>
        )}
        <time className="ml-auto" dateTime={new Date(i.at * 1000).toISOString()} title={fmtDate(i.at, lang)}>
          {fmtRelative(i.at, lang)}
        </time>
      </div>
      <p className="whitespace-pre-wrap">
        <Sensitive length={30}>{i.text}</Sensitive>
      </p>
    </li>
  )
}
