// The commands of the composer's "/" menu (SlashMenu.tsx): the session's own, then the skills of its topic.
import * as React from 'react'
import { useT } from '@/i18n'
import { useClaudeStatus, useTopicSkills, type Skill } from '@/lib/queries'
import { EFFORTS, type Effort } from '@/lib/types'
import type { SlashCommand } from './SlashMenu'
import { modelLabel } from './util'

export type SlashActions = {
  model: string
  onModel: (model: string) => void
  effort: Effort | ''
  onEffort: (effort: Effort | '') => void
  plan?: boolean
  onPlan?: () => void
  onCompact?: () => void
  onHandoff?: () => void
  onNew?: () => void
  onRename?: (title: string) => void
}

export function useSlashCommands(path: string, a: SlashActions): SlashCommand[] {
  const t = useT()
  const { data: claude } = useClaudeStatus()
  const { data: skills } = useTopicSkills(path)
  const live = React.useRef(a)
  live.current = a
  const models = claude?.models
  const def = claude?.default_model || ''
  return React.useMemo(() => {
    const out: SlashCommand[] = [
      {
        name: 'model',
        kind: 'action',
        description: t('sessions.slash.model'),
        args: [
          { value: '', label: t('sessions.model.default'), hint: def ? modelLabel(def, models) : '', current: !a.model },
          ...(models || []).map((m) => ({ value: m.id, label: m.label || modelLabel(m.id), hint: m.id, current: a.model === m.id })),
        ],
        // "/model opus" works too: an alias, an id or the beginning of a label
        run: (arg) => {
          const q = arg.trim().toLowerCase()
          const hit = !q ? '' : (models || []).find((m) => m.id === q || (m.label || '').toLowerCase().startsWith(q))?.id ?? q
          live.current.onModel(hit === t('sessions.model.default').toLowerCase() ? '' : hit)
        },
      },
      {
        name: 'effort',
        kind: 'action',
        description: t('sessions.slash.effort'),
        args: (['', ...EFFORTS] as const).map((e) => ({
          value: e || 'auto',
          label: t(`sessions.effort.long.${e || 'auto'}`),
          hint: t(`sessions.effort.hint.${e || 'auto'}`),
          current: a.effort === e,
        })),
        run: (arg) => {
          const v = arg.trim().toLowerCase()
          const level = (EFFORTS as readonly string[]).includes(v) ? (v as Effort) : ''
          live.current.onEffort(level)
        },
      },
    ]
    if (a.onPlan)
      out.push({ name: 'plan', kind: 'action', description: t(a.plan ? 'sessions.slash.planOff' : 'sessions.slash.planOn'), run: () => live.current.onPlan?.() })
    if (a.onCompact) out.push({ name: 'compact', kind: 'action', description: t('sessions.slash.compact'), run: () => live.current.onCompact?.() })
    if (a.onHandoff) out.push({ name: 'handoff', kind: 'action', description: t('sessions.slash.handoff'), run: () => live.current.onHandoff?.() })
    if (a.onNew) out.push({ name: 'new', kind: 'action', description: t('sessions.slash.new'), run: () => live.current.onNew?.() })
    if (a.onRename)
      out.push({ name: 'rename', kind: 'action', freeArg: true, description: t('sessions.slash.rename'), run: (arg) => arg && live.current.onRename?.(arg) })
    // Skills: this topic's and project's first, then the others - the product's last (Claude picks them by itself
    // when the message is about crons, agents, the server...)
    const taken = new Set(out.map((c) => c.name))
    const rank = (x: Skill) => (x.origin === 'topic' ? 0 : x.origin === 'project' ? 1 : x.name.startsWith('maxxing-') ? 3 : 2)
    for (const s of [...(skills?.skills || [])].sort((x, y) => rank(x) - rank(y))) {
      if (taken.has(s.name)) continue
      taken.add(s.name)
      out.push({ name: s.name, kind: 'skill', group: rank(s) < 2 ? 'here' : 'other', description: s.description })
    }
    return out
  }, [t, models, def, skills, a.model, a.effort, a.plan, !!a.onPlan, !!a.onCompact, !!a.onHandoff, !!a.onNew, !!a.onRename]) // eslint-disable-line react-hooks/exhaustive-deps
}
