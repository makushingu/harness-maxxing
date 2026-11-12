// Settings -> Skills (2.0.0a132): the skills Claude Code sees on this server (GET /api/skills, read-only), yours first
// with where each one lives (server, workspace, a project, a topic), then the ones shipped with Harness (refreshed by
// every update, so only open them). Changes go through Claude: "Edit with Claude" / "New skill" open a session draft.
import * as React from 'react'
import { useNavigate } from 'react-router'
import { Eye, MoreHorizontal, Plus, Search, Share2, Sparkles, WandSparkles } from 'lucide-react'
import { useSkills, type Skill } from '@/lib/queries'
import { useT } from '@/i18n'
import { Badge, Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger, EmptyState, Input, Skeleton , useContextMenu } from '@/components/ui'
import { openFileViewer } from '@/features/files/viewerStore'
import { draftUrl } from '@/features/agents/EditWithClaude'
import { CommunityLink } from './Extensions'
import { SettingsCard, SectionStack } from './ui'
import { useHarnessTopic } from './harnessTopic'

const ORDER = { topic: 0, project: 1, workspace: 2, user: 3, product: 4 } as const

/** The topic whose session edits this skill: its own topic, else the Harness topic (`fallback`, see harnessTopic.ts). */
const topicOf = (s: Skill, fallback: string) => (s.origin === 'topic' && s.project && s.topic ? `projects/${s.project}/topics/${s.topic}` : fallback)

function Where({ s }: { s: Skill }) {
  const t = useT()
  const label =
    s.origin === 'topic' ? `${s.project}/${s.topic}` : s.origin === 'project' ? s.project : s.origin === 'workspace' ? t('skills.where.workspace') : t('skills.where.user')
  return <Badge variant="muted" className="font-normal">{label}</Badge>
}

function SkillRow({ s }: { s: Skill }) {
  const t = useT()
  const navigate = useNavigate()
  const harness = useHarnessTopic()
  const mine = s.origin !== 'product'
  const ctx = useContextMenu({ disabled: !mine })
  const items = (
    <>
      <DropdownMenuItem onSelect={() => navigate(draftUrl(topicOf(s, harness), t('skills.editPrompt', { name: s.name, path: s.path })))}>
        <WandSparkles /> {t('skills.edit')}
      </DropdownMenuItem>
      <DropdownMenuItem onSelect={() => navigate(draftUrl(harness, t('skills.publishPrompt', { name: s.name, path: s.path })))}>
        <Share2 /> {t('skills.publish')}
      </DropdownMenuItem>
    </>
  )
  return (
    <li {...ctx.props} className="flex items-start gap-3 px-4 py-3" data-testid="skill-row">
      <div className="grid min-w-0 flex-1 gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[13px] font-medium [overflow-wrap:anywhere]">{s.name}</span>
          {mine && <Where s={s} />}
          {s.hidden && <Badge variant="outline" className="font-normal">{t('skills.slashOnly', { name: s.name })}</Badge>}
        </div>
        {s.description && <p className="line-clamp-2 text-[13px] text-muted-foreground" title={s.description}>{s.description}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button variant="ghost" size="sm" onClick={() => openFileViewer(s.path)} aria-label={`${t('skills.open')} ${s.name}`}>
          <Eye /> <span className="max-sm:hidden">{t('skills.open')}</span>
        </Button>
        {mine && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon-sm" aria-label={t('common.more')}>
                <MoreHorizontal />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">{items}</DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      {ctx.menu(items)}
    </li>
  )
}

function List({ items }: { items: Skill[] }) {
  return (
    <ul className="divide-y border-t">
      {items.map((s) => (
        <SkillRow key={s.path} s={s} />
      ))}
    </ul>
  )
}

export function SkillsSection() {
  const t = useT()
  const navigate = useNavigate()
  const harness = useHarnessTopic()
  const { data, isLoading } = useSkills()
  const [q, setQ] = React.useState('')
  const needle = q.trim().toLowerCase()
  const all = (data?.skills || []).filter((s) => !needle || `${s.name} ${s.description} ${s.project || ''} ${s.topic || ''}`.toLowerCase().includes(needle))
  const mine = all.filter((s) => s.origin !== 'product').sort((a, b) => ORDER[a.origin] - ORDER[b.origin] || a.name.localeCompare(b.name))
  const shipped = all.filter((s) => s.origin === 'product')
  const flush = '[&>div:last-child]:p-0 [&>div:last-child]:pt-4'
  return (
    <SectionStack>
      {(data?.skills.length ?? 0) > 8 && (
        <div className="relative max-w-sm">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('skills.search')} className="pl-8" aria-label={t('skills.search')} />
        </div>
      )}
      <SettingsCard
        title={t('skills.mine')}
        description={t('skills.mineDesc')}
        className={flush}
        actions={
          <Button variant="outline" size="sm" onClick={() => navigate(draftUrl(harness, t('skills.newPrompt')))}>
            <Plus /> {t('skills.new')}
          </Button>
        }
      >
        {isLoading ? (
          <div className="grid gap-2 p-4">
            <Skeleton className="h-12" />
            <Skeleton className="h-12" />
          </div>
        ) : !mine.length ? (
          <EmptyState compact icon={Sparkles} title={needle ? t('skills.noMatch') : t('skills.empty')} description={needle ? undefined : t('skills.emptyDesc')} />
        ) : (
          <List items={mine} />
        )}
      </SettingsCard>
      <SettingsCard title={t('skills.shipped')} description={t('skills.shippedDesc')} className={flush}>
        {isLoading ? <Skeleton className="m-4 h-12" /> : shipped.length ? <List items={shipped} /> : <p className="px-4 pb-4 text-sm text-muted-foreground">{needle ? t('skills.noMatch') : t('skills.emptyShipped')}</p>}
      </SettingsCard>
      <CommunityLink text={t('skills.community')} />
    </SectionStack>
  )
}
