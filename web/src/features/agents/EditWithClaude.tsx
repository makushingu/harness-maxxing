// A new-session draft of a topic in Sessions (/sessions?new=1&path=<topic>&prompt=<text>), its request already
// started in the composer (not sent, the cursor at the end): the owner finishes the sentence and sends. Used where
// no conversation does the work itself (an agent group, a custom Office view); an agent changes itself in its own
// conversation.

// Only a link of the app itself may type in a composer: it arms its prompt right before it navigates, and Sessions
// takes it once. A `prompt=` nobody armed (a link in a message, an address opened from outside) is ignored.
let armed: string | null = null
/** To call in the click that follows the link `url` (an app route with `prompt=`). */
export function armPrompt(url: unknown) {
  const q = typeof url === 'string' ? url.indexOf('?') : -1
  const prompt = q < 0 ? null : new URLSearchParams((url as string).slice(q + 1)).get('prompt')
  if (prompt) armed = prompt
}
export function takePrompt(prompt: string): boolean {
  const ok = armed === prompt
  armed = null
  return ok
}

/** A new session of `topic` (projects/<p>/topics/<t>) in Sessions, its composer pre-filled with `prompt`: to navigate
 *  to at once (the prompt is armed here). */
export const draftUrl = (topic: string, prompt: string) => {
  const url = `/sessions?new=1&path=${encodeURIComponent(topic)}&prompt=${encodeURIComponent(prompt)}`
  armPrompt(url)
  return url
}
