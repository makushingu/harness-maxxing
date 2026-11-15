// Microphone capture for the voice mode: 16 kHz mono 16-bit PCM frames + a level (0-1), from the chosen microphone
// (echo cancellation on, so the voice playing back is not heard as the user). A ScriptProcessor, not an AudioWorklet:
// the app's script policy only runs scripts served by this server, and a worklet module from a Blob would be refused.
import { openMic } from '../mic'

export type Capture = { stop: () => void; stream: MediaStream; rate: number }

export async function startCapture(onFrame: (pcm: Int16Array, level: number) => void, stream?: MediaStream): Promise<Capture> {
  const s = stream || (await openMic())
  const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
  const ctx = new AC()
  if (ctx.state === 'suspended') await ctx.resume().catch(() => {})
  const src = ctx.createMediaStreamSource(s)
  const node = ctx.createScriptProcessor(2048, 1, 1)
  const ratio = ctx.sampleRate / 16000
  let carry = 0
  node.onaudioprocess = (e) => {
    const input = e.inputBuffer.getChannelData(0)
    let sum = 0
    for (let i = 0; i < input.length; i++) sum += input[i] * input[i]
    const level = Math.min(1, Math.sqrt(sum / input.length) * 4)
    // Downsample by averaging (good enough for speech).
    const n = Math.floor((input.length - carry) / ratio)
    const out = new Int16Array(Math.max(0, n))
    for (let j = 0; j < n; j++) {
      const a = Math.floor(carry + j * ratio)
      const b = Math.min(input.length, Math.floor(carry + (j + 1) * ratio))
      let v = 0
      for (let k = a; k < b; k++) v += input[k]
      v = b > a ? v / (b - a) : input[a] || 0
      out[j] = Math.max(-32768, Math.min(32767, Math.round(v * 32767)))
    }
    carry = carry + n * ratio - input.length
    if (carry < 0) carry = 0
    onFrame(out, level)
  }
  src.connect(node)
  // A ScriptProcessor only runs when connected to the output: through a muted gain.
  const mute = ctx.createGain()
  mute.gain.value = 0
  node.connect(mute)
  mute.connect(ctx.destination)
  return {
    stream: s,
    rate: 16000,
    stop: () => {
      node.onaudioprocess = null
      try {
        src.disconnect()
        node.disconnect()
      } catch {
        /* already */
      }
      if (!stream) s.getTracks().forEach((t) => t.stop())
      void ctx.close().catch(() => {})
    },
  }
}

/** 16 kHz mono PCM -> a WAV file. */
export function toWav(chunks: Int16Array[], rate = 16000): Blob {
  const n = chunks.reduce((a, c) => a + c.length, 0)
  const buf = new ArrayBuffer(44 + n * 2)
  const v = new DataView(buf)
  const w = (o: number, s: string) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)))
  w(0, 'RIFF')
  v.setUint32(4, 36 + n * 2, true)
  w(8, 'WAVE')
  w(12, 'fmt ')
  v.setUint32(16, 16, true)
  v.setUint16(20, 1, true)
  v.setUint16(22, 1, true)
  v.setUint32(24, rate, true)
  v.setUint32(28, rate * 2, true)
  v.setUint16(32, 2, true)
  v.setUint16(34, 16, true)
  w(36, 'data')
  v.setUint32(40, n * 2, true)
  let o = 44
  for (const c of chunks) {
    for (let i = 0; i < c.length; i++, o += 2) v.setInt16(o, c[i], true)
  }
  return new Blob([buf], { type: 'audio/wav' })
}

export function toBase64(pcm: Int16Array): string {
  const bytes = new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)
  let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(s)
}
