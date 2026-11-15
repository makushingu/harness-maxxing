// Local voice: the browser listens (speech detection on the level, 0.4 s kept before the start) and sends each
// sentence of the user as a WAV to the server, which transcribes it, sets noise / echo / "stop" aside and asks the
// voice (a Claude model kept for the call). The voice answers, said by Piper sentence by sentence, and may hand the
// user's own words to the session ("ask") or stop it. The end of each turn of the session and news of a long one
// go through the voice too.
// Speaking over the voice, in three steps: a sound lowers its volume (it goes on); 0.8 s of real speech well over
// its echo cuts it and the user is heard to the end; then the transcript decides: noise, its own echo or a mere
// "yeah" -> it says the cut sentence again, anything else -> it answers. While the user speaks nothing new is said:
// a reply to their previous words is dropped and what they add goes with them (one answer for the whole). A tap on
// the call cuts it too.
import { callTurn, endCall, type TurnLine } from './api'
import { startCapture, toWav, type Capture } from './capture'
import type { Brain, CallPhase, Outcome, Voice, VoiceEvents } from './types'

const PREROLL_FRAMES = 10 // ~0.4 s at 2048 samples / 48 kHz
const START_FRAMES = 3 // frames above the threshold before it counts as speech
// While the voice speaks the mic also hears it (less with echo cancellation, almost nothing with headphones): the
// threshold follows what the mic picks up of the voice.
const BARGE_FRAMES = 4 // ~0.17 s: a short echo peak is not the user
const DUCK_VOLUME = 0.3 // the voice while it is not sure the user speaks
const CONFIRM_MS = 800 // speech well over the echo for this long: the voice stops
const CONFIRM_FRAMES = 6
const DUCK_QUIET_MS = 500 // quiet again before that: it was noise, the voice is back to full volume
const DUCK_MAX_MS = 3000 // a low voice that goes on this long is cut anyway (the transcript decides)
const BARGE_MIN = 0.07
const BARGE_OVER_ECHO = 1.6 // the echo itself is filtered out on the server (`saying`)
const MIN_SPEECH_MS = 300
const MAX_SPEECH_MS = 60_000

type TurnBody = { audio?: Blob; event?: string; outcome?: Outcome; note?: string; tool?: string }

export class LocalVoice implements Voice {
  private cap: Capture | null = null
  private audio = new Audio()
  private queue: { url: string; say: string }[] = []
  private playing = false // a sentence is playing (or paused in the middle)
  private paused = false // cut while the user speaks (the sentence is said again if it was not them)
  private ducked = false // a sound over the voice, not sure yet it is the user: lower volume, still speaking
  private turn: AbortController | null = null
  private hearing = false // a turn with the user's audio is open and its transcript is not known yet
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
    const cap = await startCapture((pcm, level) => this.frame(pcm, level))
    if (this.closed) return cap.stop() // hung up while the mic was being opened
    this.cap = cap
    this.phase('listening')
  }

  private frame(pcm: Int16Array, level: number) {
    if (this.closed) return
    this.ev.level?.(level)
    const now = performance.now()
    const overVoice = this.playing && !this.paused
    const start = overVoice ? Math.max(BARGE_MIN, this.floor * 2.5, this.echo * BARGE_OVER_ECHO) : Math.max(0.12, this.floor * 2.5)
    if (this.rec) {
      this.rec.push(pcm)
      if (level >= start * 0.6 || level >= Math.max(0.12, this.floor * 2.5) * 0.6) this.lastLoud = now
      const long = now - this.recStart
      if (this.ducked) {
        if (level >= Math.max(0.09, this.echo * 2.2)) this.strong++
        const sure = long >= CONFIRM_MS && this.strong >= CONFIRM_FRAMES && now - this.lastLoud < 300
        if (sure || long >= DUCK_MAX_MS) {
          // It is the user: the voice stops (paused: it says its sentence again if the transcript is only noise)
          this.ducked = false
          this.paused = true
          this.audio.pause()
          this.phase('hearing')
        } else if (now - this.lastLoud >= DUCK_QUIET_MS) {
          this.rec = null // a short noise, a cough, a "hm": the voice was never cut
          this.unduck()
        }
        return
      }
      if (now - this.lastLoud >= this.silenceMs || long >= MAX_SPEECH_MS) this.endUtterance(long)
      return
    }
    this.preroll.push(pcm)
    if (this.preroll.length > PREROLL_FRAMES) this.preroll.shift()
    if (level >= start) {
      if (++this.above >= (overVoice ? BARGE_FRAMES : START_FRAMES)) {
        if (overVoice) {
          this.ducked = true // it may only be noise: the voice goes on, lower, until it is sure
          this.audio.volume = DUCK_VOLUME
        }
        this.heardOver = this.playing ? this.saying : ''
        this.strong = 0
        this.rec = [...this.preroll]
        this.preroll = []
        this.recStart = now
        this.lastLoud = now
        this.above = 0
        if (!overVoice) this.phase('hearing')
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

  private unduck() {
    this.ducked = false
    this.audio.volume = 1
  }

  private abortTurn() {
    this.turn?.abort()
    this.turn = null
    this.hearing = false
  }

  private async runTurn(body: TurnBody) {
    this.abortTurn()
    const ctrl = new AbortController()
    this.turn = ctrl
    this.turnSaid = false
    this.hearing = !!body.audio
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
        if (await this.handle(line, ctrl)) break // noise: nothing to answer
        if (line.say) said += (said ? ' ' : '') + line.say
      }
    } catch (e) {
      if (ctrl.signal.aborted || this.closed) return
      this.ev.error((e as Error)?.message || String(e))
      this.resume()
    } finally {
      if (this.turn === ctrl) {
        this.turn = null
        this.hearing = false
      }
    }
    if (ctrl.signal.aborted || this.closed) return
    if (said) this.ev.caption('voice', said)
    this.settle()
  }

  /** One line of a turn; true when the turn ends here (nothing to answer). */
  private async handle(line: TurnLine, ctrl: AbortController): Promise<boolean> {
    if (line.language) this.language = line.language
    if (line.heard !== undefined) {
      this.hearing = false
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
    // The user is speaking: nothing new is said over them (their next words may change the answer)
    if ((this.rec && !this.ducked) || this.hearing) {
      this.playing = false
      return
    }
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
    this.unduck()
    if (this.playing) {
      // the cut sentence again from its start (the middle of a sentence is hard to follow)
      this.phase('speaking')
      this.audio.currentTime = 0
      void this.audio.play().catch(() => this.playNext(true))
    } else this.playNext(false)
  }

  /** Everything said or being prepared is dropped. */
  private dropSpeech() {
    this.queue = []
    this.playing = false
    this.paused = false
    this.unduck()
    this.audio.pause()
  }

  /** Nothing playing, heard or prepared: the next end of turn that waited, else listening. */
  private settle() {
    if (this.closed) return
    if (!this.playing && !this.paused && this.queue.length) {
      this.playNext(false) // sentences held while the user spoke
      return
    }
    if (this.playing || this.paused || this.rec || this.turn) return
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
