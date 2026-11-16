// OpenAI Realtime voice: WebRTC straight to OpenAI with the short-lived token from this server (the instructions, the
// tools and the voice are locked in it). Audio both ways over the peer connection; events and tool calls over the
// "oai-events" data channel. It converses and hands the user's own words over with ask_session (Relay).
// A connection that fails (network, the session's time limit) is replaced by a new one with a new token; OpenAI does
// not carry the conversation over, so the new one is told the last lines of the call (Relay.recap).
import type { CallStart } from './api'
import { Relay } from './cloud'
import { openMic } from '../mic'
import { runTool, type Brain, type Outcome, type Voice, type VoiceEvents } from './types'

type Cloud = Extract<CallStart, { mode: 'cloud' }>

export class OpenAIVoice implements Voice {
  private pc: RTCPeerConnection | null = null
  private dc: RTCDataChannel | null = null
  private mic: MediaStream | null = null
  private audio = new Audio()
  private speaking = false
  private pending: string[] = []
  private closed = false
  private meter = 0
  private relay: Relay
  private renewing = false
  private meterCtx: AudioContext | null = null
  private lostTimer = 0

  constructor(
    private c: Cloud,
    private brain: Brain,
    private ev: VoiceEvents,
    language: string,
    private renew: (resume?: string) => Promise<Cloud>,
  ) {
    this.audio.autoplay = true
    this.relay = new Relay(brain, language)
  }

  async start() {
    const mic = await openMic()
    if (this.closed) return mic.getTracks().forEach((t) => t.stop()) // hung up while the mic was being opened
    this.mic = mic
    this.levels(mic)
    await this.connect(this.c)
    if (this.closed) return this.close()
    this.ev.phase('listening')
  }

  /** One peer connection to OpenAI; resolves once its event channel is open. */
  private async connect(c: Cloud) {
    const pc = new RTCPeerConnection()
    this.pc = pc
    pc.ontrack = (e) => {
      this.audio.srcObject = e.streams[0]
      void this.audio.play().catch(() => {})
    }
    this.mic!.getTracks().forEach((t) => pc.addTrack(t, this.mic!))
    const dc = pc.createDataChannel('oai-events')
    this.dc = dc
    dc.onmessage = (m) => this.event(JSON.parse(m.data))
    // Opened, or failed: a connection that never opens (ICE failed, no answer) is an error, never a wait forever.
    let live = false
    let fail: (e: Error) => void = () => {}
    const opened = new Promise<void>((resolve, reject) => {
      dc.onopen = () => resolve()
      fail = reject
    })
    const openTimer = window.setTimeout(() => fail(new Error('OpenAI: the connection did not open')), 15_000)
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    const r = await fetch(c.url, {
      method: 'POST',
      body: offer.sdp,
      headers: { Authorization: `Bearer ${c.token}`, 'Content-Type': 'application/sdp' },
      signal: AbortSignal.timeout(15_000),
    })
    if (!r.ok) throw new Error(`OpenAI: ${(await r.text()).slice(0, 200) || r.status}`)
    await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() })
    pc.onconnectionstatechange = () => {
      if (this.closed || this.pc !== pc) return
      window.clearTimeout(this.lostTimer)
      if (!live) {
        if (pc.connectionState === 'failed' || pc.connectionState === 'closed') fail(new Error('OpenAI: the connection failed'))
      } else if (pc.connectionState === 'failed') void this.reconnect()
      // "disconnected" often comes back by itself: replaced only if it lasts
      else if (pc.connectionState === 'disconnected') this.lostTimer = window.setTimeout(() => void this.reconnect(), 4000)
    }
    dc.onclose = () => {
      if (!live) fail(new Error('OpenAI: the connection closed'))
      else if (!this.closed && this.pc === pc) void this.reconnect()
    }
    try {
      await opened
    } finally {
      window.clearTimeout(openTimer)
    }
    live = true
  }

  private async reconnect() {
    if (this.renewing || this.closed) return
    this.renewing = true
    window.clearTimeout(this.lostTimer)
    const old = this.pc
    this.pc = null
    this.dc = null
    old?.close()
    this.speaking = false
    for (let attempt = 1; !this.closed; attempt++) {
      try {
        const c = await this.renew()
        if (this.closed) break
        await this.connect(c)
        const recap = this.relay.recap()
        if (recap) this.send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text: recap }] } })
        this.ev.phase('listening')
        break
      } catch (e) {
        ;(this.pc as RTCPeerConnection | null)?.close()
        this.pc = null
        if (attempt >= 3) {
          this.ev.error(`OpenAI: ${(e as Error)?.message || 'the call was cut'}`)
          this.ev.ended?.()
          break
        }
        await new Promise((r) => setTimeout(r, 1000 * attempt))
      }
    }
    this.renewing = false
  }

  /** Level meter of the microphone (the peer connection does not give one). */
  private levels(s: MediaStream) {
    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new AC()
      this.meterCtx = ctx
      const an = ctx.createAnalyser()
      an.fftSize = 512
      ctx.createMediaStreamSource(s).connect(an)
      const buf = new Uint8Array(an.fftSize)
      const tick = () => {
        if (this.closed) return void ctx.close().catch(() => {})
        an.getByteTimeDomainData(buf)
        let sum = 0
        for (let i = 0; i < buf.length; i++) sum += ((buf[i] - 128) / 128) ** 2
        this.ev.level?.(Math.min(1, Math.sqrt(sum / buf.length) * 4))
        this.meter = requestAnimationFrame(tick)
      }
      this.meter = requestAnimationFrame(tick)
    } catch {
      /* no meter */
    }
  }

  private send(obj: unknown) {
    if (this.dc?.readyState === 'open') this.dc.send(JSON.stringify(obj))
  }

  private event(e: { type: string; transcript?: string; name?: string; call_id?: string; arguments?: string; error?: { message?: string } }) {
    switch (e.type) {
      case 'input_audio_buffer.speech_started':
        this.ev.phase('hearing')
        break
      case 'input_audio_buffer.speech_stopped':
        this.ev.phase('thinking')
        break
      case 'conversation.item.input_audio_transcription.completed':
        if (e.transcript?.trim()) {
          this.ev.caption('you', e.transcript.trim())
          void this.relay.heard(e.transcript)
        }
        break
      case 'response.output_audio_transcript.done':
        if (e.transcript?.trim()) {
          this.ev.caption('voice', e.transcript.trim())
          this.relay.said(e.transcript)
        }
        break
      case 'output_audio_buffer.started':
        this.speaking = true
        this.ev.phase('speaking')
        break
      case 'output_audio_buffer.stopped':
      case 'output_audio_buffer.cleared':
        this.speaking = false
        this.ev.phase('listening')
        if (this.pending.length) this.sendEvent(this.pending.shift()!)
        break
      case 'response.function_call_arguments.done':
        void this.tool(e.name || '', e.call_id || '', e.arguments || '{}')
        break
      case 'error':
        this.ev.error(`OpenAI: ${e.error?.message || 'error'}`)
        break
    }
  }

  private async tool(name: string, callId: string, raw: string) {
    let args: Record<string, unknown> = {}
    try {
      args = JSON.parse(raw)
    } catch {
      /* no arguments */
    }
    let output: string
    try {
      output = name === 'ask_session' ? await this.relay.handOver() : await runTool(this.brain, name, args)
    } catch (e) {
      output = `Failed: ${(e as Error)?.message || e}`
    }
    this.send({ type: 'conversation.item.create', item: { type: 'function_call_output', call_id: callId, output } })
    this.send({ type: 'response.create' })
  }

  private sendEvent(text: string) {
    this.send({ type: 'conversation.item.create', item: { type: 'message', role: 'user', content: [{ type: 'input_text', text }] } })
    this.send({ type: 'response.create' })
  }

  progress(note: string, tool: string) {
    if (this.speaking) return
    this.sendEvent(`[Session working]\n${note.slice(0, 2000) || `Using the tool ${tool}`}`)
  }

  notify(answer: string, outcome: Outcome) {
    const text = this.relay.finished(answer, outcome)
    if (!text) return
    if (this.speaking) this.pending.push(text)
    else this.sendEvent(text)
  }

  interrupt() {
    this.send({ type: 'response.cancel' })
    this.send({ type: 'output_audio_buffer.clear' })
  }

  close() {
    this.closed = true
    window.clearTimeout(this.lostTimer)
    cancelAnimationFrame(this.meter)
    void this.meterCtx?.close().catch(() => {})
    this.meterCtx = null
    this.dc?.close()
    this.pc?.close()
    this.mic?.getTracks().forEach((t) => t.stop())
    this.audio.srcObject = null
  }
}
