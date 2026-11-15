// Local voice: the browser listens (speech detection on the level, 0.4 s kept before the start) and sends each
// sentence of the user as a WAV to the server, which transcribes it, sets noise / echo / "stop" aside and asks the
// voice (a Claude model kept for the call). The voice answers, said by Piper sentence by sentence, and may hand the
// user's own words to the session ("ask") or stop it. The end of each turn of the session and news of a long one
// go through the voice too.
// Turn-taking: "turns" (default) = the mic is off while the voice speaks, a tap on the call cuts it; "call" = speak
// over the voice: it pauses, stops when it is really the user (1 s of speech well over its echo, or a transcript
// that is not its own words), and goes on where it was after noise.
import { callTurn, endCall, type TurnLine } from './api'
import { startCapture, toWav, type Capture } from './capture'
import type { Brain, CallPhase, Outcome, Voice, VoiceEvents } from './types'

const PREROLL_FRAMES = 10 // ~0.4 s at 2048 samples / 48 kHz
const START_FRAMES = 3 // frames above the threshold before it counts as speech
// While the voice speaks the mic also hears it (less with echo cancellation, almost nothing with headphones): in
// "call" mode the threshold follows what the mic picks up of the voice.
const BARGE_FRAMES = 4 // ~0.17 s: a short echo peak is not the user
const BARGE_MIN = 0.07
const BARGE_OVER_ECHO = 1.6 // the echo itself is filtered out on the server (`saying`)
const SURE_SPEECH_MS = 1000
const MIN_SPEECH_MS = 300
const MAX_SPEECH_MS = 60_000

type TurnBody = { audio?: Blob; event?: string; outcome?: Outcome; note?: string; tool?: string }

export class LocalVoice implements Voice {
  private cap: Capture | null = null
  private audio = new Audio()
  private queue: { url: string; say: string }[] = []
  private playing = false // a sentence is playing (or paused in the middle)
  private paused = false // "call" mode: paused while the user speaks
  private turn: AbortController | null = null
  private turnSaid = false // the open turn already gave something to say
  private events: TurnBody[] = [] // ends of turns waiting for the voice to be free
  private muteNext = false // the turn the user stopped: its end is not read out
  private saying = ''
  private heardOver = ''
  private strong = 0
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
    private language: string,
    private turnMode: 'turns' | 'call',
    private silenceMs: number,
    private brain: Brain,
    private ev: VoiceEvents,
  ) {
    this.audio.onended = () => this.playNext(true)
    this.audio.onerror = () => this.playNext(true)
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
    // "turns": the mic does not count while the voice speaks (its own voice, or the user waiting for the end)
    if (this.turnMode === 'turns' && this.playing && !this.rec) {
      this.above = 0
      this.preroll = []
      return
    }
    const overVoice = this.playing && !this.paused
    const start = overVoice ? Math.max(BARGE_MIN, this.floor * 2.5, this.echo * BARGE_OVER_ECHO) : Math.max(0.12, this.floor * 2.5)
    if (this.rec) {
      this.rec.push(pcm)
      if (level >= start * 0.6 || level >= Math.max(0.12, this.floor * 2.5) * 0.6) this.lastLoud = now
      const long = now - this.recStart
      if (this.paused && level >= Math.max(0.09, this.echo * 2.2)) this.strong++
      if (this.paused && long >= SURE_SPEECH_MS && this.strong >= 8 && now - this.lastLoud < 300) this.dropSpeech()
      if (now - this.lastLoud >= this.silenceMs || long >= MAX_SPEECH_MS) this.endUtterance(long)
      return
    }
    this.preroll.push(pcm)
    if (this.preroll.length > PREROLL_FRAMES) this.preroll.shift()
    if (level >= start) {
      if (++this.above >= (overVoice ? BARGE_FRAMES : START_FRAMES)) {
        if (overVoice) {
          this.paused = true // it may only be noise: paused until the sentence is known
          this.audio.pause()
        }
        this.heardOver = this.playing ? this.saying : ''
        this.strong = 0
        this.rec = [...this.preroll]
        this.preroll = []
        this.recStart = now
        this.lastLoud = now
        this.above = 0
        this.phase('hearing')
      }
    } else {
      this.above = 0
      if (!overVoice) this.floor = this.floor * 0.97 + level * 0.03
      // What the microphone hears of the voice: rises fast, falls slowly.
      else this.echo = level > this.echo ? this.echo * 0.7 + level * 0.3 : this.echo * 0.98 + level * 0.02
    }
  }

  private endUtterance(long: number) {
    const chunks = this.rec || []
    this.rec = null
    if (long - this.silenceMs < MIN_SPEECH_MS) {
      this.resume()
      return
    }
    // A reply being prepared to what the user said before is dropped: what they add goes with it (the server keeps
    // what was not handed over yet).
    if (this.turn && !this.turnSaid) this.abortTurn()
    void this.runTurn({ audio: toWav(chunks) })
  }

  private abortTurn() {
    this.turn?.abort()
    this.turn = null
  }

  private async runTurn(body: TurnBody) {
    this.abortTurn()
    const ctrl = new AbortController()
    this.turn = ctrl
    this.turnSaid = false
    if (!this.playing) this.phase('thinking')
    const heardOver = this.heardOver
    this.heardOver = ''
    let said = ''
    try {
      const stream = callTurn(
        this.call,
        { ...body, context: this.brain.status(), busy: this.brain.busy(), saying: body.audio ? heardOver : undefined },
        ctrl.signal,
      )
      for await (const line of stream) {
        if (ctrl.signal.aborted || this.closed) return
        if (await this.handle(line, ctrl)) return
        if (line.say) said += (said ? ' ' : '') + line.say
      }
    } catch (e) {
      if (ctrl.signal.aborted || this.closed) return
      this.ev.error((e as Error)?.message || String(e))
      this.resume()
    } finally {
      if (this.turn === ctrl) this.turn = null
    }
    if (ctrl.signal.aborted || this.closed) return
    if (said) this.ev.caption('voice', said)
    this.settle()
  }

  /** One line of a turn; true when the turn ends here (nothing to answer). */
  private async handle(line: TurnLine, ctrl: AbortController): Promise<boolean> {
    if (line.language) this.language = line.language
    if (line.heard !== undefined) {
      if (line.kind === 'empty') {
        this.resume() // noise, or the voice's own echo: it goes on where it was
        return true
      }
      this.ev.caption('you', line.heard)
      this.dropSpeech() // the user really spoke: what the voice was saying is over (it stays written)
      this.events = this.events.filter((e) => e.outcome !== 'progress')
    }
    if (line.error) this.ev.error(line.error)
    if (line.action?.type === 'ask' && line.action.request) {
      const r = await this.brain.ask(line.action.request, this.language)
      if (r.startsWith('The message could not')) this.ev.error(r)
    }
    if (line.action?.type === 'stop') {
      if (this.brain.busy()) this.muteNext = true
      this.events = []
      await this.brain.stop()
    }
    if (line.url && !ctrl.signal.aborted) {
      this.turnSaid = true
      this.queue.push({ url: line.url, say: line.say || '' })
      if (!this.playing) this.playNext(false)
    }
    return false
  }

  private playNext(ended: boolean) {
    if (ended) this.playing = false
    if (this.paused || this.closed) return
    const next = this.queue.shift()
    if (!next) {
      this.playing = false
      this.settle()
      return
    }
    if (!this.playing) this.echo = this.floor
    this.playing = true
    this.phase('speaking')
    this.saying = next.say
    this.audio.src = next.url
    void this.audio.play().catch(() => this.playNext(true))
  }

  /** The voice goes on where it was paused. */
  private resume() {
    if (!this.paused) {
      this.settle()
      return
    }
    this.paused = false
    if (this.playing) {
      this.phase('speaking')
      void this.audio.play().catch(() => this.playNext(true))
    } else this.playNext(false)
  }

  /** Everything said or being prepared is dropped. */
  private dropSpeech() {
    this.queue = []
    this.playing = false
    this.paused = false
    this.audio.pause()
  }

  /** Nothing playing, heard or prepared: the next end of turn that waited, else listening. */
  private settle() {
    if (this.closed || this.playing || this.paused || this.rec || this.turn) return
    const next = this.events.shift()
    if (next) void this.runTurn(next)
    else if (this.phaseNow !== 'listening') this.phase('listening')
  }

  notify(answer: string, outcome: Outcome) {
    if (this.closed) return
    if (this.muteNext) {
      this.muteNext = false
      return
    }
    this.events = this.events.filter((e) => e.outcome !== 'progress')
    this.events.push({ event: answer, outcome })
    this.settle()
  }

  progress(note: string, tool: string) {
    if (this.closed || this.playing || this.paused || this.rec || this.turn || this.events.length) return
    void this.runTurn({ outcome: 'progress', note, tool })
  }

  /** A tap on the call: the voice stops talking and listens. */
  interrupt() {
    this.abortTurn()
    this.dropSpeech()
    this.events = this.events.filter((e) => e.outcome !== 'progress')
    if (!this.rec) this.phase('listening')
  }

  close() {
    this.closed = true
    this.interrupt()
    this.events = []
    this.cap?.stop()
    this.cap = null
    void endCall(this.call)
  }
}
