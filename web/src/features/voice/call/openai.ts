// OpenAI Realtime voice: WebRTC straight to OpenAI with the short-lived token from this server (the instructions, the
// tools and the voice are locked in it). Audio both ways over the peer connection; events and tool calls over the
// "oai-events" data channel. It converses and hands the user's own words over with ask_session (Relay).
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

  constructor(
    private c: Cloud,
    private brain: Brain,
    private ev: VoiceEvents,
    language: string,
  ) {
    this.audio.autoplay = true
    this.relay = new Relay(brain, language)
  }

  async start() {
    const pc = new RTCPeerConnection()
    this.pc = pc
    pc.ontrack = (e) => {
      this.audio.srcObject = e.streams[0]
      void this.audio.play().catch(() => {})
    }
    this.mic = await openMic()
    this.mic.getTracks().forEach((t) => pc.addTrack(t, this.mic!))
    this.levels(this.mic)
    const dc = pc.createDataChannel('oai-events')
    this.dc = dc
    dc.onmessage = (m) => this.event(JSON.parse(m.data))
    const opened = new Promise<void>((resolve) => (dc.onopen = () => resolve()))
    const offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    const r = await fetch(this.c.url, {
      method: 'POST',
      body: offer.sdp,
      headers: { Authorization: `Bearer ${this.c.token}`, 'Content-Type': 'application/sdp' },
    })
    if (!r.ok) throw new Error(`OpenAI: ${(await r.text()).slice(0, 200) || r.status}`)
    await pc.setRemoteDescription({ type: 'answer', sdp: await r.text() })
    pc.onconnectionstatechange = () => {
      if (!this.closed && (pc.connectionState === 'failed' || pc.connectionState === 'disconnected')) this.ev.error('OpenAI: the call was cut')
    }
    await opened
    this.ev.phase('listening')
  }

  /** Level meter of the microphone (the peer connection does not give one). */
  private levels(s: MediaStream) {
    try {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new AC()
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
    cancelAnimationFrame(this.meter)
    this.dc?.close()
    this.pc?.close()
    this.mic?.getTracks().forEach((t) => t.stop())
    this.audio.srcObject = null
  }
}
