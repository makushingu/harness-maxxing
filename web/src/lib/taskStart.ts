/* The task a new session is started for (Tasks -> Start a session): linked to that session once it exists
 * (pages/sessions/Column.tsx), when its first message still carries the title of the task - the user may have
 * started something else in that new session. Keyed like the drafts: `new:<topic path>`. */
const waiting = new Map<string, { id: string; title: string }>()
export function giveTask(k: string, id: string, title: string) {
  waiting.set(k, { id, title })
}
export const hasTask = (k: string) => waiting.has(k)
export function takeTask(k: string, message: string): string | null {
  const w = waiting.get(k)
  waiting.delete(k)
  return w && message.includes(w.title) ? w.id : null
}
