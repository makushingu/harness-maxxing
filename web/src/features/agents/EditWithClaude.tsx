// A new-session draft of a topic in Sessions (/sessions?new=1&path=<topic>&prompt=<text>), its request already
// started in the composer (not sent, the cursor at the end): the owner finishes the sentence and sends. Used where
// no conversation does the work itself (an agent group, a custom Office view); an agent changes itself in its own
// conversation.

/** A new session of `topic` (projects/<p>/topics/<t>) in Sessions, its composer pre-filled with `prompt`. */
export const draftUrl = (topic: string, prompt: string) => `/sessions?new=1&path=${encodeURIComponent(topic)}&prompt=${encodeURIComponent(prompt)}`
