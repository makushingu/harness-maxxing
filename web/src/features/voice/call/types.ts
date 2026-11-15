// The voice mode's two halves: a Voice (talker: local, OpenAI or Gemini) and the Brain it drives (the session).

export type CallPhase = 'connecting' | 'listening' | 'hearing' | 'thinking' | 'speaking' | 'paused'

/** What the voice can do on the session (run by the browser, see VoiceCall.tsx). */
export interface Brain {
  /** Sends a message to the session (queued when it is busy). */
  ask(request: string): Promise<string>
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
}

export interface Voice {
  start(): Promise<void>
  /** A turn of the session ended: the voice tells the user. */
  notify(answer: string): void
  /** Stop talking now and listen. */
  interrupt(): void
  close(): void
}

export function runTool(brain: Brain, name: string, args: Record<string, unknown>): Promise<string> | string {
  if (name === 'ask_session') return brain.ask(String(args.request || ''))
  if (name === 'session_status') return brain.status()
  if (name === 'stop_session') return brain.stop()
  if (name === 'read_last_answer') return brain.lastAnswer() || 'No answer yet.'
  return `Unknown tool ${name}`
}
