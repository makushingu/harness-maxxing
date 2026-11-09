// The topic where Settings opens a session draft about Harness itself (new widget / page / skill, publish, update).
// system/harness on recent workspaces; older ones have system/update (before 2.0.0a33) or no `system` project at
// all: then another topic the user has (general/inbox, any inbox, the first one), never a missing one (its draft
// could not be sent).
import { useWorkspace } from '@/lib/queries'
import type { WorkspaceTree } from '@/lib/types'

export const HARNESS_TOPIC = 'projects/system/topics/harness'
const PREFERRED = [HARNESS_TOPIC, 'projects/system/topics/update', 'projects/system/topics/extensions', 'projects/general/topics/inbox']

export function harnessTopic(ws: WorkspaceTree | undefined): string {
  const paths = (ws?.projects ?? []).flatMap((p) => p.topics.map((tp) => tp.path))
  if (!paths.length) return HARNESS_TOPIC // tree not loaded yet (or empty): the usual topic
  return PREFERRED.find((p) => paths.includes(p)) ?? paths.find((p) => p.endsWith('/topics/inbox')) ?? paths[0]
}

export function useHarnessTopic(): string {
  const { data: ws } = useWorkspace()
  return harnessTopic(ws)
}
