// Cloud voices (OpenAI Realtime, Gemini Live) follow the same rule as the local one: the provider is only the voice.
// Each sentence it transcribes goes to the session word for word (sorted on the server first: noise, "ok", "stop",
// language requests), and the end of each turn of the session is given to it to read out.
import { sortSentence } from './api'
import type { Brain, Outcome } from './types'

export class Relay {
  private expecting = false
  private muteNext = false

  constructor(
    private brain: Brain,
    public language: string,
  ) {}

  /** What the voice just said: a question makes the next "ok" an answer for the session. */
  said(text: string) {
    this.expecting = text.trim().endsWith('?')
  }

  /** A sentence of the user, as transcribed by the provider. */
  async heard(text: string) {
    text = text.trim()
    if (!text) return
    const s = await sortSentence(text, this.language, this.expecting).catch(() => ({ kind: 'ask' as const, language: this.language }))
    this.language = s.language
    if (s.kind === 'empty' || s.kind === 'skip') return
    this.expecting = false
    if (s.kind === 'stop') {
      if (this.brain.busy()) this.muteNext = true
      await this.brain.stop()
    } else if (s.kind === 'ask') await this.brain.ask(text, this.language)
  }

  /** The message given to the voice when a turn of the session ends; null when the user stopped that turn. */
  finished(answer: string, outcome: Outcome): string | null {
    if (this.muteNext) {
      this.muteNext = false
      return null
    }
    if (outcome === 'failed') return `[Session finished: it failed]\n${answer.slice(0, 6000) || 'No details.'}`
    if (outcome === 'done' || !answer.trim()) return '[Session finished]\n(Done, no written answer.)'
    return `[Session finished]\n${answer.slice(0, 6000)}`
  }
}
