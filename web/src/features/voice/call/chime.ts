// The two short tones of a call: rising when it is connected, falling when it ends. Made with Web Audio (no file);
// the context is opened on the tap that starts the call, so phones let it play.
let ctx: AudioContext | null = null

/** Call it from the tap that starts the call. */
export function unlockChime() {
  try {
    if (!ctx) {
      const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      ctx = new AC()
    }
    void ctx.resume().catch(() => {})
  } catch {
    ctx = null
  }
}

function tones(freqs: number[]) {
  if (!ctx) unlockChime()
  const c = ctx
  if (!c) return
  const t0 = c.currentTime + 0.02
  freqs.forEach((f, i) => {
    const at = t0 + i * 0.11
    const osc = c.createOscillator()
    const gain = c.createGain()
    osc.type = 'sine'
    osc.frequency.value = f
    gain.gain.setValueAtTime(0, at)
    gain.gain.linearRampToValueAtTime(0.16, at + 0.015)
    gain.gain.exponentialRampToValueAtTime(0.001, at + 0.16)
    osc.connect(gain).connect(c.destination)
    osc.start(at)
    osc.stop(at + 0.18)
  })
}

export const chimeOn = () => tones([660, 880])
export const chimeOff = () => tones([660, 440])
