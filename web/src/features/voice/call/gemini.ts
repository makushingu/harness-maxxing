// Gemini Live voice: a WebSocket straight to Google with the short-lived token from this server (the instructions,
// the tools and the voice are locked in it). In: 16 kHz PCM; out: 24 kHz PCM played as it comes; the model hears
// the user over itself (barge-in). It converses and hands the user's own words over with ask_session (Relay).
// Google ends a connection after about 10 minutes (goAway): a new one is opened with a new token and the handle of
// the last state (session resumption), so the conversation goes on. A tap mutes the reply under way to its end (Live
// has no "cancel": what it still sends of that reply is dropped).
import type { CallStart } from './api'
import { Relay } from './cloud'
import { startCapture, toBase64, type Capture } from './capture'
import { runTool, type Brain, type CallPhase, type Outcome, type Voice, type VoiceEvents } from './types'

type Cloud = Extract<CallStart, { mode: 'cloud' }>
type FnCall = { id: string; name: string; args?: Record<string, unknown> }

export class GeminiVoice implements Voice {
  private ws: WebSocket | null = null
  private cap: Capture | null = null
  private out: AudioContext | null = null
  private sources: AudioBufferSourceNode[] = []
  private until = 0
  private batch: Int16Array[] = []
  private ready = false
  private closed = false
  private heard = ''
  private said = ''
  private pending: string[] = []
  private idleTimer = 0
  private relay: Relay
  private handle = '' // Gemini's handle of the last state, to resume after a reconnection
  private renewing = false
  private failures = 0
  private muted = false // tapped: the rest of the current reply is not played
  private replying = false // a reply of the model is coming (between its first part and turnComplete)

  constructor(
    private c: Cloud,
    private brain: Brain,
    private ev: VoiceEvents,
    language: string,
    private renew: (resume?: string) => Promise<Cloud>,
  ) {
    this.relay = new Relay(brain, language)
  }

  async start() {
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
    this.out = new AC({ sampleRate: 24000 })
    await this.out.resume().catch(() => {})
    await this.connect(this.c)
    if (this.closed) return this.close() // hung up while connecting
    const cap = await startCapture((pcm, level) => {
      this.ev.level?.(level)
      this.batch.push(pcm)
      if (this.batch.length > 25) this.batch.shift() // reconnecting: about the last second is kept, not the whole wait
      if (this.batch.length < 3 || !this.ws || this.ws.readyState !== WebSocket.OPEN) return
      const n = this.batch.reduce((a, b) => a + b.length, 0)
      const all = new Int16Array(n)
      let o = 0
      for (const b of this.batch) all.set(b, (o += b.length) - b.length)
      this.batch = []
      this.ws.send(JSON.stringify({ realtimeInput: { audio: { data: toBase64(all), mimeType: 'audio/pcm;rate=16000' } } }))
    })
    if (this.closed) return cap.stop()
    this.cap = cap
    this.ev.phase('listening')
  }

  /** One connection to Gemini; resolves once its setup is done. */
  private connect(c: Cloud): Promise<void> {
    this.ready = false
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(`${c.url}?access_token=${encodeURIComponent(c.token)}`)
      this.ws = ws
      // no setup answer: an error (the reconnection tries again), never a wait forever
      const timer = window.setTimeout(() => {
        if (!this.ready && this.ws === ws) {
          reject(new Error('Gemini: no answer'))
          ws.close()
        }
      }, 15_000)
      ws.onopen = () => ws.send(JSON.stringify({ setup: { model: `models/${c.model}` } }))
      ws.onerror = () => reject(new Error('Gemini: connection failed'))
      ws.onclose = (e) => {
        if (this.ws !== ws) return // an older connection, already replaced
        if (!this.ready) reject(new Error(`Gemini: ${e.reason || 'connection closed'}`))
        else if (!this.closed) void this.reconnect(e.reason)
      }
      ws.onmessage = async (m) => {
        if (this.ws !== ws) return
        const text = typeof m.data === 'string' ? m.data : await (m.data as Blob).text()
        const msg = JSON.parse(text)
        if (msg.setupComplete && !this.ready) {
          window.clearTimeout(timer)
          this.ready = true
          resolve()
          return
        }
        this.message(msg)
      }
    })
  }

  /** The connection ended (time limit, network): a new one, the conversation carried over. */
  private async reconnect(reason?: string) {
    if (this.renewing || this.closed) return
    this.renewing = true
    const old = this.ws
    this.ws = null
    try {
      old?.close()
    } catch {
      /* closed */
    }
    this.flushCaptions()
    // what the old connection was saying is over: its end never comes on the new one
    this.stopAudio()
    this.muted = this.replying = false
    this.heard = this.said = ''
    while (!this.closed) {
      try {
        const c = await this.renew(this.handle)
        if (this.closed) break
        await this.connect(c)
        // No handle (cut before Gemini gave one): the new connection is told what was said.
        const recap = this.handle ? null : this.relay.recap()
        if (recap) (this.ws as WebSocket | null)?.send(JSON.stringify({ clientContent: { turns: [{ role: 'user', parts: [{ text: recap }] }], turnComplete: false } }))
        this.failures = 0
        break
      } catch (e) {
        // a handle refused (expired): start again without it, from the recap
        if (this.handle) this.handle = ''
        else if (++this.failures >= 3) {
          this.ev.error(`Gemini: ${reason || (e as Error)?.message || 'the call ended'}`)
          this.ev.ended?.()
          break
        }
        await new Promise((r) => setTimeout(r, 1000 * this.failures))
      }
    }
    this.renewing = false
  }

  private message(msg: {
    serverContent?: { modelTurn?: { parts?: { inlineData?: { data: string } }[] }; interrupted?: boolean; turnComplete?: boolean; inputTranscription?: { text?: string }; outputTranscription?: { text?: string } }
    toolCall?: { functionCalls?: FnCall[] }
    goAway?: unknown
    sessionResumptionUpdate?: { newHandle?: string; resumable?: boolean }
  }) {
    const ru = msg.sessionResumptionUpdate
    if (ru?.resumable && ru.newHandle) this.handle = ru.newHandle
    const sc = msg.serverContent
    if (sc && this.muted) {
      // the reply the user cut by a tap: dropped to its end
      if (sc.inputTranscription?.text) this.heard += sc.inputTranscription.text
      if (sc.turnComplete || sc.interrupted) {
        this.muted = false
        this.said = ''
        this.flushCaptions()
      }
    } else if (sc) {
      if (sc.inputTranscription?.text) {
        this.heard += sc.inputTranscription.text
        this.ev.phase('hearing')
      }
      if (sc.outputTranscription?.text) this.said += sc.outputTranscription.text
      if (sc.modelTurn?.parts?.length) this.replying = true
      for (const p of sc.modelTurn?.parts || []) if (p.inlineData?.data) this.play(p.inlineData.data)
      if (sc.interrupted) this.stopAudio()
      if (sc.turnComplete || sc.interrupted) this.replying = false
      if (sc.turnComplete || sc.interrupted) this.flushCaptions()
    }
    if (msg.toolCall?.functionCalls?.length) void this.tools(msg.toolCall.functionCalls)
    if (msg.goAway) void this.reconnect() // the time limit of this connection: the next one carries the call on
  }

  private flushCaptions() {
    if (this.heard.trim()) {
      this.ev.caption('you', this.heard.trim())
      void this.relay.heard(this.heard)
    }
    if (this.said.trim()) {
      this.ev.caption('voice', this.said.trim())
      this.relay.said(this.said)
    }
    this.heard = this.said = ''
  }

  private async tools(calls: FnCall[]) {
    this.flushCaptions()
    this.ev.phase('thinking')
    const functionResponses = []
    for (const fc of calls) {
      let result: string
      try {
        result = fc.name === 'ask_session' ? await this.relay.handOver() : await runTool(this.brain, fc.name, fc.args || {})
      } catch (e) {
        result = `Failed: ${(e as Error)?.message || e}`
      }
      functionResponses.push({ id: fc.id, name: fc.name, response: { result } })
    }
    this.ws?.send(JSON.stringify({ toolResponse: { functionResponses } }))
  }

  private play(b64: string) {
    const ctx = this.out
    if (!ctx) return
    const bin = atob(b64)
    const n = bin.length >> 1
    const buf = ctx.createBuffer(1, n, 24000)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < n; i++) {
      const v = bin.charCodeAt(2 * i) | (bin.charCodeAt(2 * i + 1) << 8)
      ch[i] = (v >= 0x8000 ? v - 0x10000 : v) / 32768
    }
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(ctx.destination)
    const at = Math.max(ctx.currentTime + 0.02, this.until)
    src.start(at)
    this.until = at + buf.duration
    this.sources.push(src)
    src.onended = () => {
      this.sources = this.sources.filter((s) => s !== src)
      if (!this.sources.length) this.idle()
    }
    window.clearTimeout(this.idleTimer)
    this.ev.phase('speaking')
  }

  private idle() {
    window.clearTimeout(this.idleTimer)
    this.idleTimer = window.setTimeout(() => {
      if (this.sources.length || this.closed) return
      this.ev.phase('listening')
      const next = this.pending.shift()
      if (next) this.sendEvent(next)
    }, 400)
  }

  private stopAudio() {
    for (const s of this.sources) {
      try {
        s.stop()
      } catch {
        /* ended */
      }
    }
    this.sources = []
    this.until = 0
  }

  private sendEvent(text: string) {
    this.ws?.send(JSON.stringify({ clientContent: { turns: [{ role: 'user', parts: [{ text }] }], turnComplete: true } }))
    this.ev.phase('thinking')
  }

  progress(note: string, tool: string) {
    if (this.sources.length) return
    this.sendEvent(`[Session working]\n${note.slice(0, 2000) || `Using the tool ${tool}`}`)
  }

  notify(answer: string, outcome: Outcome) {
    const text = this.relay.finished(answer, outcome)
    if (!text) return
    // Not over its own sentence: a clientContent cuts what the model is saying.
    if (this.sources.length) this.pending.push(text)
    else this.sendEvent(text)
  }

  interrupt() {
    this.stopAudio()
    if (this.replying) this.muted = true
    this.replying = false
    this.ev.phase('listening' as CallPhase)
  }

  close() {
    this.closed = true
    this.stopAudio()
    this.cap?.stop()
    this.cap = null
    try {
      this.ws?.close()
    } catch {
      /* closed */
    }
    void this.out?.close().catch(() => {})
  }
}
