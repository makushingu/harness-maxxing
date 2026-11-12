// An Office view brought by an extension (manifest "agents_view" + agents-view.html, listed in the view menu of the
// Office): its HTML drawn in the sandboxed frame of HTML widgets (HtmlWidget: scripts, no same-origin, no cookies),
// which this host gives three more things:
//   maxxing.data / maxxing.onData(fn)  the Office, pushed again at every change (below: OfficeData);
//   maxxing.app(path)                  a read-only GET of /api/agents or /api/agents/layout (the raw API);
//   maxxing.navigate(route)            a route of the Agents page: an agent's `route` (its page), its `chat_route`
//                                      (its conversation next to the Office), `/agents?new=1` (New agent).
// Nothing else of the app is reachable from the frame; its own api.py stays reachable with maxxing.api().
import * as React from 'react'
import { useLang, useT } from '@/i18n'
import { useLocation } from 'react-router'
import { agentRoute, useWorkspace } from '@/lib/queries'
import type { Agent } from '@/lib/types'
import { HtmlWidget, type FrameHost } from '@/pages/dashboard/HtmlWidget'
import { OUTFIT } from './Avatar'
import { avatarSvg, normalize } from './pixels'
import { statusOf } from './parts'
import type { AgentsLayoutApi, ProjectGroup } from './layout'
import { maskOfficeData } from './officePresentation'
import { usePresentation } from '@/components/ui'

// The raw /api/agents is not offered: it holds trigger prompts and key names, the pushed data is enough.
const READS = ['/api/agents/layout']
const ROUTES = ['/agents']

/** What the frame gets in maxxing.data (documented for extension authors in docs/user/13-page-extensions.md). */
function officeData(groups: ProjectGroup[], colorOf: (p: string) => string, emojis: Map<string, string>, t: ReturnType<typeof useT>, lang: string, here: string) {
  const agent = (a: Agent) => {
    const s = statusOf(a, t, lang)
    const last = a.last_run
    return {
      path: a.path,
      project: a.project,
      topic: a.topic,
      name: a.name,
      display_name: a.display_name,
      description: a.description,
      enabled: a.enabled,
      model: a.model,
      status: s.id,
      status_text: s.text,
      running: a.running_now || 0,
      waiting: a.waiting || 0,
      unread: a.thread_unread || 0,
      cost_today: a.cost_today || 0,
      last_run: last ? { at: last.at, kind: last.kind, ok: last.ok ?? null, text: (last.text || '').slice(0, 300) } : null,
      avatar: normalize(a.avatar),
      avatar_svg: avatarSvg(normalize(a.avatar), !a.enabled),
      route: agentRoute(a),
      chat_route: `${here}?chat=${encodeURIComponent(a.path)}`,
    }
  }
  return {
    lang,
    new_agent_route: '/agents?new=1',
    projects: groups.map(({ project: p, agents }) => ({
      name: p,
      emoji: emojis.get(p) || '',
      color: OUTFIT[colorOf(p)],
      agents: agents.map(agent),
    })),
  }
}

export function OfficeCustom({ ext, groups, layout }: { ext: { id: string; name: string }; groups: ProjectGroup[]; layout: AgentsLayoutApi }) {
  const t = useT()
  const lang = useLang()
  const { data: ws } = useWorkspace()
  const emojis = React.useMemo(() => new Map((ws?.projects || []).map((p) => [p.name, p.emoji || ''])), [ws])
  // Pushed again only when what it says changed (the groups are rebuilt at every render of the Office).
  const here = useLocation().pathname                  // /agents or /agents/office: the Office stays, its panel opens
  const presentation = usePresentation()
  const json = JSON.stringify(maskOfficeData(officeData(groups, layout.colorOf, emojis, t, lang, here), presentation))
  const data = React.useMemo(() => JSON.parse(json) as unknown, [json])
  const host = React.useMemo<FrameHost>(() => ({ reads: READS, routes: ROUTES, data }), [data])
  const base = `/ext/${encodeURIComponent(ext.id)}`
  return (
    <div data-testid="agents-office-custom" data-ext={ext.id}>
      <HtmlWidget key={ext.id} id={ext.id} src={`${base}/agents-view.html`} frame={`${base}/agents-view-frame`} height={640} maxHeight={6000} title={ext.name} host={host} />
    </div>
  )
}
