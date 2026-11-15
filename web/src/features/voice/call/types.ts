// The voice mode's two halves: a Voice (local, OpenAI or Gemini: it only carries the call) and the Brain it carries
// (the session, which does the thinking: every sentence of the user goes to it).

export type CallPhase = 'connecting' | 'listening' | 'hearing' | 'thinking' | 'speaking' | 'paused'

/** How a turn of the session ended: its answer, a failure, or no written answer. */
export type Outcome = 'answer' | 'failed' | 'done' | 'progress'

/** What the voice can do on the session (run by the browser, see VoiceCall.tsx). */
export interface Brain {
  /** Sends what the user said to the session, word for word (queued when it is busy). `lang`: the call's language. */
  ask(text: string, lang?: string): Promise<string>
  /** Whether the session is working now. */
  busy(): boolean
  /** One line: working or not, for how long, its last steps, the messages waiting. */
  status(): string
  stop(): Promise<string>
  lastAnswer(): string
}

export interface VoiceEvents {
  phase(p: CallPhase): void
  /** A line of the conversation, for the captions. */
  caption(who: 'you' | 'voice', text: string): void
  error(message: string): void
  level?(level: number): void
  /** The call cannot go on (its connection could not be renewed): the page hangs it up. */
  ended?(): void
}

export interface Voice {
  start(): Promise<void>
  /** A turn of the session ended: the voice reads it out. */
  notify(answer: string, outcome: Outcome): void
  /** The session is still working: say in one sentence what it does (its last note, else its last tool), when the
   * voice has nothing else to say. */
  progress(note: string, tool: string): void
  /** Stop talking now and listen. */
  interrupt(): void
  close(): void
}

export function runTool(brain: Brain, name: string, _args: Record<string, unknown>): Promise<string> | string {
  if (name === 'session_status') return brain.status()
  if (name === 'stop_session') return brain.stop()
  if (name === 'read_last_answer') return brain.lastAnswer() || 'No answer yet.'
  return `Unknown tool ${name}`
}
