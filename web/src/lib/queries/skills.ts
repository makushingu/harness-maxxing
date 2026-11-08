import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { qk } from './keys'

/** Where a skill comes from: `product` = shipped and refreshed by every update (read-only). */
export type SkillOrigin = 'product' | 'user' | 'workspace' | 'project' | 'topic'

export interface Skill {
  name: string
  folder: string
  description: string
  origin: SkillOrigin
  path: string
  /** `disable-model-invocation: true`: Claude never picks it alone, only `/name` starts it. */
  hidden: boolean
  project?: string
  topic?: string
}

/** The skills of this install (Settings -> Skills). Under `workspace`, so the live bus refreshes the list. */
export function useSkills() {
  return useQuery({ queryKey: qk.skills, queryFn: () => api.get<{ skills: Skill[] }>('/api/skills') })
}
