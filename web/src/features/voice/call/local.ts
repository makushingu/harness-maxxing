// Local voice: the browser listens (speech detection on the level, 0.4 s kept before the start), sends each sentence of
// the user as a WAV to the server, which transcribes it, asks the voice (a small Claude model) and answers with
// actions and sentences said by Piper, played one after the other. Speaking over the voice cuts it (barge-in).
import { callTurn, endCall, type TurnLine } from './api'
import { startCapture, toWav, type Capture } from './capture'
import type { Brain, CallPhase, Voice, VoiceEvents } from './types'

const PREROLL_FRAMES = 10 // ~0.4 s at 2048 samples / 48 kHz
const START_FRAMES = 3 // frames above the threshold before it counts as speech
// While the voice speaks the microphone also hears it (less with echo cancellation, almost nothing with headphones):
// the threshold follows what the microphone picks up of the voice, so speaking normally over it cuts it.
const BARGE_FRAMES = 4 // ~0.17 s: a short echo peak is not the user
const BARGE_MIN = 0.09
const BARGE_OVER_ECHO = 2.2
const END_SILENCE_MS = 900
const MIN_SPEECH_MS = 300
const MAX_SPEECH_MS = 60_000

export class LocalVoice implements Voice {
  private cap: Capture | null = null
  private audio = new Audio()
  private queue: string[] = []
  private playing = false
  private turn: AbortController | null = null
  private turnOpen = false
  private pending: string[] = []
  private floor = 0.04
  private echo = 0
  private above = 0
  private preroll: Int16Array[] = []
  private rec: Int16Array[] | null = null
  private recStart = 0
  private lastLoud = 0
  private closed = false
  private phaseNow: CallPhase = 'connecting'

  constructor(
    private call: string,
    private brain: Brain,
    private ev: VoiceEvents,
  ) {
    this.audio.onended = () => this.playNext()
    this.audio.onerror = () => this.playNext()
  }

  private phase(p: CallPhase) {
    this.phaseNow = p
    this.ev.phase(p)
  }

  async start() {
    // Unlocks playback on phones: this runs from the tap that started the call.
    this.audio.src = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA='
    void this.audio.play().catch(() => {})
    this.cap = await startCapture((pcm, level) => this.frame(pcm, level))
    this.phase('listening')
  }

  private frame(pcm: Int16Array, level: number) {
    if (this.closed) return
    this.ev.level?.(level)
    const now = performance.now()
    const busySpeaking = this.playing
    const start = busySpeaking
      ? Math.max(BARGE_MIN, this.floor * 2.5, this.echo * BARGE_OVER_ECHO)
      : Math.max(0.12, this.floor * 2.5)
    if (this.rec) {
      this.rec.push(pcm)
      if (level >= start * 0.6) this.lastLoud = now
      const long = now - this.recStart
      if (now - this.lastLoud >= END_SILENCE_MS || long >= MAX_SPEECH_MS) this.endUtterance(long)
      return
    }
    this.preroll.push(pcm)
    if (this.preroll.length > PREROLL_FRAMES) this.preroll.shift()
    if (level >= start) {
      if (++this.above >= (busySpeaking ? BARGE_FRAMES : START_FRAMES)) {
        // The user speaks: whatever the voice was saying or preparing stops.
        if (this.playing || this.turnOpen) this.interrupt()
        this.rec = [...this.preroll]
        this.preroll = []
        this.recStart = now
        this.lastLoud = now
        this.above = 0
        this.phase('hearing')
      }
    } else {
      this.above = 0
      if (!busySpeaking) this.floor = this.floor * 0.97 + level * 0.03
      // What the microphone hears of the voice: rises fast, falls slowly.
      else this.echo = level > this.echo ? this.echo * 0.7 + level * 0.3 : this.echo * 0.98 + level * 0.02
    }
  }

  private endUtterance(long: number) {
    const chunks = this.rec || []
    this.rec = null
    if (long - END_SILENCE_MS < MIN_SPEECH_MS) {
      this.phase(this.playing ? 'speaking' : 'listening')
      return
    }
    void this.runTurn({ audio: toWav(chunks), context: this.brain.status() })
  }

  private async runTurn(body: { audio?: Blob; event?: string; context?: string }) {
    this.turn?.abort()
    const ctrl = new AbortController()
    this.turn = ctrl
    this.turnOpen = true
    this.phase('thinking')
    let said = ''
    try {
      for await (const line of callTurn(this.call, body, ctrl.signal)) {
        if (ctrl.signal.aborted || this.closed) return
        await this.handle(line)
        if (line.say) said += (said ? ' ' : '') + line.say
      }
    } catch (e) {
      if (ctrl.signal.aborted || this.closed) return
      this.ev.error((e as Error)?.message || String(e))
    } finally {
      if (this.turn === ctrl) {
        this.turn = null
        this.turnOpen = false
      }
    }
    if (ctrl.signal.aborted || this.closed) return
    if (said) this.ev.caption('voice', said)
    if (!this.playing && !this.rec) this.afterTurn()
  }

  private async handle(line: TurnLine) {
    if (line.heard !== undefined && line.heard) this.ev.caption('you', line.heard)
    if (line.error) this.ev.error(line.error)
    if (line.action?.type === 'ask') await this.brain.ask(line.action.request)
    if (line.action?.type === 'stop') await this.brain.stop()
    if (line.url) {
      this.queue.push(line.url)
      if (!this.playing) this.playNext()
    }
  }

  private playNext() {
    const next = this.queue.shift()
    if (!next || this.closed) {
      this.playing = false
      if (!this.turnOpen && !this.rec) this.afterTurn()
      return
    }
    if (!this.playing) this.echo = this.floor
    this.playing = true
    this.phase('speaking')
    this.audio.src = next
    void this.audio.play().catch(() => this.playNext())
  }

  /** Done talking: an announcement that waited goes now, else back to listening. */
  private afterTurn() {
    const ev = this.pending.shift()
    if (ev) void this.runTurn({ event: ev })
    else if (this.phaseNow !== 'listening') this.phase('listening')
  }

  notify(answer: string) {
    if (this.closed) return
    if (this.turnOpen || this.playing || this.rec) this.pending.push(answer)
    else void this.runTurn({ event: answer })
  }

  interrupt() {
    this.turn?.abort()
    this.turn = null
    this.turnOpen = false
    this.queue = []
    this.playing = false
    this.audio.pause()
    if (!this.rec) this.phase('listening')
  }

  close() {
    this.closed = true
    this.interrupt()
    this.cap?.stop()
    this.cap = null
    void endCall(this.call)
  }
}
