// Local voice: the browser listens (speech detection on the level, 0.4 s kept before the start) and sends each
// sentence of the user as a WAV to the server, which transcribes and sorts it. A real sentence goes to the session
// word for word, and a short acknowledgement ready in advance plays at once; the session's answer is read out
// sentence by sentence (Piper). Speaking over the voice pauses it: it resumes where it was when it was only noise
// or "ok", and stops when the user really said something (at once when they speak on for a second).
import { endCall, hear, speak, type SayLine } from './api'
import { startCapture, toWav, type Capture } from './capture'
import type { Brain, CallPhase, Outcome, Voice, VoiceEvents } from './types'

const PREROLL_FRAMES = 10 // ~0.4 s at 2048 samples / 48 kHz
const START_FRAMES = 3 // frames above the threshold before it counts as speech
// While the voice speaks the microphone also hears it (less with echo cancellation, almost nothing with headphones):
// the threshold follows what the microphone picks up of the voice, so speaking normally over it pauses it.
const BARGE_FRAMES = 4 // ~0.17 s: a short echo peak is not the user
const BARGE_MIN = 0.09
const BARGE_OVER_ECHO = 2.2
const END_SILENCE_MS = 900
const MIN_SPEECH_MS = 300
// Speaking over the voice pauses it; speech that goes on this long is surely the user, not noise: the voice stops
// for good at once, without waiting for the transcript.
const SURE_SPEECH_MS = 1000
const MAX_SPEECH_MS = 60_000

export class LocalVoice implements Voice {
  private cap: Capture | null = null
  private audio = new Audio()
  private queue: string[] = []
  private playing = false // a sentence is playing (or paused in the middle)
  private paused = false // paused while the user speaks
  private reading: AbortController | null = null // the answer being read out
  private answers: { answer: string; outcome: Outcome }[] = []
  private hearing = 0 // sentences sent to the server, not sorted yet
  private heardChain: Promise<void> = Promise.resolve()
  private muteNext = false // the turn the user stopped: its end is not read out
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
    const busySpeaking = this.playing && !this.paused
    const start = busySpeaking ? Math.max(BARGE_MIN, this.floor * 2.5, this.echo * BARGE_OVER_ECHO) : Math.max(0.12, this.floor * 2.5)
    if (this.rec) {
      this.rec.push(pcm)
      if (level >= start * 0.6) this.lastLoud = now
      const long = now - this.recStart
      if (this.paused && long >= SURE_SPEECH_MS && now - this.lastLoud < 300) this.dropSpeech()
      if (now - this.lastLoud >= END_SILENCE_MS || long >= MAX_SPEECH_MS) this.endUtterance(long)
      return
    }
    this.preroll.push(pcm)
    if (this.preroll.length > PREROLL_FRAMES) this.preroll.shift()
    if (level >= start) {
      if (++this.above >= (busySpeaking ? BARGE_FRAMES : START_FRAMES)) {
        // The user speaks: the voice pauses (it may only be noise) until the sentence is known.
        if (this.playing && !this.paused) {
          this.paused = true
          this.audio.pause()
        }
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
      this.resume()
      return
    }
    const wav = toWav(chunks)
    this.hearing++
    this.phase('thinking')
    // In order: a sentence said while the previous one is being heard waits for it.
    this.heardChain = this.heardChain.then(() => this.sorted(wav)).finally(() => {
      this.hearing--
      this.settle()
    })
  }

  private async sorted(wav: Blob) {
    let h
    try {
      h = await hear(this.call, wav, this.brain.busy())
    } catch (e) {
      if (!this.closed) this.ev.error((e as Error)?.message || String(e))
      this.resume()
      return
    }
    if (this.closed) return
    this.language = h.language || this.language
    if (h.kind === 'empty' || h.kind === 'skip') {
      this.resume() // noise, "ok", "thanks": the voice goes on where it was
      return
    }
    this.ev.caption('you', h.text)
    this.dropSpeech() // a real sentence: what the voice was saying is over (it stays written)
    if (h.say) this.enqueue(h.say)
    if (h.kind === 'stop') {
      if (this.brain.busy()) this.muteNext = true
      this.answers = []
      await this.brain.stop()
    } else if (h.kind === 'ask') {
      const r = await this.brain.ask(h.text, this.language)
      if (r.startsWith('The message could not')) this.ev.error(r)
    }
  }

  private enqueue(line: SayLine) {
    if (line.error) this.ev.error(line.error)
    if (!line.url) return
    this.queue.push(line.url)
    if (!this.playing) this.playNext(false)
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
    this.audio.src = next
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

  /** Everything said so far is dropped (the answer being read too). */
  private dropSpeech() {
    this.reading?.abort()
    this.reading = null
    this.queue = []
    this.playing = false
    this.paused = false
    this.audio.pause()
  }

  /** Nothing playing, heard or read: the next answer that waited, else listening. */
  private settle() {
    if (this.closed || this.playing || this.paused || this.rec || this.hearing || this.reading) return
    const next = this.answers.shift()
    if (next) void this.read(next)
    else if (this.phaseNow !== 'listening') this.phase('listening')
  }

  private async read({ answer, outcome }: { answer: string; outcome: Outcome }) {
    const ctrl = new AbortController()
    this.reading = ctrl
    this.phase('thinking')
    let said = ''
    try {
      for await (const line of speak(this.call, answer, outcome, ctrl.signal)) {
        if (ctrl.signal.aborted || this.closed) return
        this.enqueue(line)
        if (line.say) said += (said ? ' ' : '') + line.say
      }
    } catch (e) {
      if (!ctrl.signal.aborted && !this.closed) this.ev.error((e as Error)?.message || String(e))
    } finally {
      if (this.reading === ctrl) this.reading = null
    }
    if (ctrl.signal.aborted || this.closed) return
    if (said) this.ev.caption('voice', said)
    this.settle()
  }

  notify(answer: string, outcome: Outcome) {
    if (this.closed) return
    if (this.muteNext) {
      this.muteNext = false
      return
    }
    this.answers.push({ answer, outcome })
    this.settle()
  }

  interrupt() {
    this.dropSpeech()
    this.answers = []
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
