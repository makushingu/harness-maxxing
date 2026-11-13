// Scopes of the Harness Browser's tabs: who sees a tab (`me`, `topic:projects/<p>/topics/<t>`, `project:projects/<p>`,
// `agent:projects/<p>/topics/<t>/agents/<a>` = that agent only).
import { Bot, FolderOpen, Hash, Lock } from 'lucide-react'
import type { BrowserScope, BrowserTab } from '@/lib/types'

export const ME: BrowserScope = 'me'

export const topicScope = (path: string) => {
  const m = /^(projects\/[^/]+\/topics\/[^/]+)/.exec(path || '')
  return m ? `topic:${m[1]}` : ME
}
const AGENT = /^(projects\/[^/]+\/topics\/[^/]+\/agents\/[^/]+)/
export const agentScope = (path: string) => {
  const m = AGENT.exec(path || '')
  return m ? `agent:${m[1]}` : ME
}
export const projectScope = (path: string) => {
  const m = /^(projects\/[^/]+)/.exec(path || '')
  return m ? `project:${m[1]}` : ME
}

/** "acme/blog" for a topic, "acme" for a project, "writer" for an agent, "" for me. */
export function scopeName(scope: BrowserScope): string {
  const [kind, where = ''] = scope.split(/:(.*)/s)
  if (kind === 'topic') return where.replace(/^projects\//, '').replace('/topics/', '/')
  if (kind === 'project') return where.replace(/^projects\//, '')
  if (kind === 'agent') return where.split('/agents/')[1] || ''
  return ''
}

/** The topic of an agent's scope ("acme/blog"), "" for the others. */
export const scopeTopic = (scope: BrowserScope) =>
  scope.startsWith('agent:') ? scopeName(topicScope(scope.slice(6))) : ''

export const scopeKind = (scope: BrowserScope): 'me' | 'topic' | 'project' | 'agent' =>
  scope.startsWith('topic:') ? 'topic' : scope.startsWith('project:') ? 'project' : scope.startsWith('agent:') ? 'agent' : 'me'

export const ScopeIcon = (scope: BrowserScope) => ({ me: Lock, topic: Hash, project: FolderOpen, agent: Bot })[scopeKind(scope)]

/** Does a tab of this scope show for a topic / an agent folder? An agent: only its own tabs. */
export function scopeCovers(scope: BrowserScope, path: string): boolean {
  if (scope === ME || !path) return false
  if (AGENT.test(path)) return scope === agentScope(path)
  return scope === topicScope(path) || scope === projectScope(path)
}

/** The tab a session last used, else the newest tab its folder sees. */
export function tabOfSession(tabs: BrowserTab[], session: string, path?: string): BrowserTab | undefined {
  const own = tabs.filter((t) => t.by.sid === session).sort((a, b) => b.used - a.used)
  if (own.length) return own[0]
  return path ? tabs.filter((t) => scopeCovers(t.scope, path)).sort((a, b) => b.used - a.used)[0] : undefined
}
