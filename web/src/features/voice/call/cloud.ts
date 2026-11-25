// Cloud voices (OpenAI Realtime, Gemini Live) follow the same rules as the local one: the model converses and hands
// work over with the tool ask_session(), which sends the user's own words (its transcription of them), never a
// rewrite. "Stop", noise and language requests are sorted on the server, without the model.
import { sortSentence } from './api'
import type { Brain, Outcome } from './types'

const MAX_PENDING = 4

export class Relay {
  private expecting = false
  private muteNext = false
  private pending: string[] = [] // what the user said since the last hand-over
  private recent: string[] = [] // the last lines of the call, given back to a new connection
  private heardSeq = 0 // sentences heard, in order
  private languageSeq = 0 // the sentence whose sorting set the language: an older one sorted later never undoes it

  constructor(
    private brain: Brain,
    public language: string,
  ) {}

  /** What the voice just said: a question makes the next "ok" an answer. */
  said(text: string) {
    this.expecting = text.trim().endsWith('?')
    this.remember('You', text)
  }

  private remember(who: string, text: string) {
    if (!text.trim()) return
    this.recent = [...this.recent, `${who}: ${text.trim().slice(0, 600)}`].slice(-16)
  }

  /** What a new connection is told when the provider could not carry the conversation over; null if nothing yet. */
  recap(): string | null {
    if (!this.recent.length) return null
    return `[The connection was renewed in the middle of the call: go on from here, do not greet again]\n${this.recent.join('\n')}`
  }

  /** A sentence of the user, as transcribed by the provider. */
  async heard(text: string) {
    text = text.trim()
    if (!text) return
    this.remember('User', text)
    this.pending.push(text) // at once: the model may call ask_session before the sorting comes back
    this.pending = this.pending.slice(-MAX_PENDING)
    const seq = ++this.heardSeq
    const s = await sortSentence(text, this.language, this.expecting).catch(() => ({ kind: 'ask' as const, language: this.language }))
    if (seq > this.languageSeq) {
      this.languageSeq = seq
      this.language = s.language
    }
    if (s.kind === 'empty' || s.kind === 'stop') this.pending = this.pending.filter((t) => t !== text)
    if (s.kind === 'stop') {
      if (this.brain.busy()) this.muteNext = true
      await this.brain.stop()
    }
  }

  /** ask_session(): the user's own words go to the session. */
  async handOver(): Promise<string> {
    // the provider's transcription of the user may come just after its tool call
    for (let i = 0; i < 15 && !this.pending.length; i++) await new Promise((r) => setTimeout(r, 100))
    const words = this.pending.join('\n')
    this.pending = []
    if (!words) return 'Nothing new was said to hand over.'
    return this.brain.ask(words, this.language)
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
