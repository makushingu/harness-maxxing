// Presentation mode for the Office views of extensions: the frame never sees the mode itself, so the data pushed to
// it is masked here (names, roles, last results, cost) and `presentation: true` tells the view to hide what it draws
// on its own. Routes and paths stay: the view needs them to open an agent, it never shows them.
const dots = (n: number) => '•'.repeat(n)

type Agent = Record<string, unknown> & { last_run?: { text?: string } | null }
type Data = Record<string, unknown> & { projects: { name: string; agents: Agent[] }[] }

export function maskOfficeData<T>(data: T, on: boolean): T {
  if (!on) return data
  const d = data as unknown as Data
  return {
    ...d,
    presentation: true,
    projects: d.projects.map((p, i) => ({
      ...p,
      name: `${dots(6)} ${i + 1}`,
      agents: p.agents.map((a) => ({
        ...a,
        project: dots(6),
        topic: dots(6),
        name: dots(6),
        display_name: dots(8),
        description: '',
        cost_today: 0,
        last_run: a.last_run ? { ...a.last_run, text: '' } : null,
      })),
    })),
  } as unknown as T
}
