// "Show me" in What's new: CHANGELOG.md bullets ending with `[Show me](#show:<id>)` get a button that plays the
// showcase <id> below with the guided tour's spotlight (tour/Tour.tsx), then leaves the user there to try it.
// A new important feature = one entry here + its `show.<id>.*` texts + the link in CHANGELOG.md. A link whose id
// is not here (an older build) is dropped from the text.
import { showDiagram } from '@/components/ui/diagram'
import { sessionsList, type TourStep } from '@/tour/steps'
import { useTouchNav } from '@/components/shell/TouchNav'

const DEMO_DIAGRAM = `flowchart LR
  A[Question] --> B{Claude}
  B -->|reads| C[Files]
  B -->|runs| D[Tools]
  C --> E[Answer]
  D --> E`

export const SHOWCASES: Record<string, TourStep[]> = {
  look: [{ id: 'look', targets: ['accent'], title: 'show.look.title', body: 'show.look.body', route: (c) => (c.pathname === '/settings/general' ? null : '/settings/general') }],
  diagram: [{ id: 'diagram', targets: [], title: 'show.diagram.title', body: 'show.diagram.body', cta: 'show.try', after: () => showDiagram(DEMO_DIAGRAM) }],
  'text-zoom': [{ id: 'text-zoom', targets: [], title: 'show.textZoom.title', body: 'show.textZoom.body' }],
  'file-menu': [{ id: 'file-menu', targets: [], title: 'show.fileMenu.title', body: 'show.fileMenu.body' }],
  'msg-actions': [{ id: 'msg-actions', targets: [], title: 'show.msgActions.title', body: 'show.msgActions.body' }],
  'video-quality': [{ id: 'video-quality', targets: [], title: 'show.videoQuality.title', body: 'show.videoQuality.body' }],
  'git-branch-menu': [{ id: 'git-branch-menu', targets: [], title: 'show.gitBranchMenu.title', body: 'show.gitBranchMenu.body' }],
  'dashboard-motion': [{ id: 'dashboard-motion', targets: [], title: 'show.dashMotion.title', body: 'show.dashMotion.body', route: (c) => (c.pathname === '/' ? null : '/') }],
  git: [{ id: 'git', targets: [], title: 'show.git.title', body: 'show.git.body', route: (c) => (c.pathname === '/git' ? null : '/git') }],
  infra: [{ id: 'infra', targets: [], title: 'show.infra.title', body: 'show.infra.body', route: (c) => (c.pathname === '/settings/features' ? null : '/settings/features') }],
  'infra-servers': [{ id: 'infra-servers', targets: [], title: 'show.infraServers.title', body: 'show.infraServers.body', route: (c) => (c.pathname === '/infra' ? null : '/infra?tab=servers') }],
  twofa: [{ id: 'twofa', targets: [], title: 'show.twofa.title', body: 'show.twofa.body', route: (c) => (c.pathname === '/settings/security' ? null : '/settings/security') }],
  'infra-domains': [{ id: 'infra-domains', targets: [], title: 'show.infraDomains.title', body: 'show.infraDomains.body', route: (c) => (c.pathname === '/infra' ? null : '/infra?tab=domains') }],
  mcp: [{ id: 'mcp', targets: [], title: 'show.mcp.title', body: 'show.mcp.body', route: (c) => (c.pathname === '/settings/mcp' ? null : '/settings/mcp') }],
  'idle-compact': [{ id: 'idle-compact', targets: ['idle-compact'], title: 'show.idleCompact.title', body: 'show.idleCompact.body', route: (c) => (c.pathname === '/settings/claude' ? null : '/settings/claude') }],
  'claude-auto-update': [{ id: 'claude-auto-update', targets: ['claude-auto-update'], title: 'show.claudeAutoUpdate.title', body: 'show.claudeAutoUpdate.body', route: (c) => (c.pathname === '/settings/claude' ? null : '/settings/claude') }],
  tasks: [{ id: 'tasks', targets: ['tasks-projects'], title: 'show.tasks.title', body: 'show.tasks.body', route: (c) => (c.pathname === '/tasks' ? null : '/tasks?project=overview') }],
  'topic-permissions': [{ id: 'topic-permissions', targets: ['tree'], title: 'show.permissions.title', body: 'show.permissions.body', route: sessionsList, before: (c) => c.mobile && useTouchNav.getState().setPanel('sessions') }],
  'pc-browser': [{ id: 'pc-browser', targets: ['pc-browser'], title: 'show.pcBrowser.title', body: 'show.pcBrowser.body', route: (c) => (c.pathname === '/settings/mcp' ? null : '/settings/mcp') }],
  'mobile-header': [{ id: 'mobile-header', targets: [], title: 'show.mobileHeader.title', body: 'show.mobileHeader.body' }],
  'touch-nav': [{ id: 'touch-nav', targets: ['touch-sessions', 'nav'], title: 'show.touchNav.title', body: 'show.touchNav.body', before: (c) => c.mobile && useTouchNav.getState().setPanel(null) }],
}

export const SHOW_HREF = '#show:'
/** `[label](#show:<id>)` links of a changelog body: labelled in the UI language, removed when the showcase does
 *  not exist here. */
export const showLinks = (md: string, label: string) =>
  md.replace(/\s*\[[^\]\n]*\]\(#show:([\w-]+)\)/g, (_m, id: string) => (SHOWCASES[id] ? ` [${label}](${SHOW_HREF}${id})` : ''))
/** Markdown classes that draw those links as pills (40 px high on touch screens). */
export const SHOW_LINK_CLASS = "[&_a[href^='#show:']]:ml-1 [&_a[href^='#show:']]:inline-flex [&_a[href^='#show:']]:h-6 [&_a[href^='#show:']]:items-center [&_a[href^='#show:']]:rounded-full [&_a[href^='#show:']]:bg-primary/12 [&_a[href^='#show:']]:px-2.5 [&_a[href^='#show:']]:text-xs [&_a[href^='#show:']]:font-medium [&_a[href^='#show:']]:text-primary [&_a[href^='#show:']]:no-underline [&_a[href^='#show:']]:transition-colors [&_a[href^='#show:']:hover]:bg-primary/20 pointer-coarse:[&_a[href^='#show:']]:h-10"
/** `Markdown` onLink for those links: `before` runs first (closing a dialog), then the spotlight starts. */
export const showcaseLink = (start: (steps: TourStep[]) => void, before?: () => void) => (href: string) => {
  const steps = href.startsWith(SHOW_HREF) ? SHOWCASES[href.slice(SHOW_HREF.length)] : undefined
  if (!steps) return null
  return () => {
    before?.()
    setTimeout(() => start(steps), before ? 200 : 0)
  }
}
