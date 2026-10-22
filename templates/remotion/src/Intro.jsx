import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from 'remotion'
import { loadFont } from '@remotion/google-fonts/Inter'

const { fontFamily } = loadFont()

export const Intro = ({ title, subtitle }) => {
  const frame = useCurrentFrame()
  const { fps, durationInFrames } = useVideoConfig()
  const pop = spring({ frame, fps, config: { damping: 200 } })
  const fade = interpolate(frame, [20, 40], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' })
  const out = interpolate(frame, [durationInFrames - 20, durationInFrames], [1, 0], { extrapolateLeft: 'clamp' })
  return (
    <AbsoluteFill style={{ background: 'radial-gradient(circle at 30% 20%, #1e3a8a, #0a0a0f 70%)', fontFamily,
      color: 'white', justifyContent: 'center', alignItems: 'center', opacity: out }}>
      <div style={{ fontSize: 120, fontWeight: 800, letterSpacing: -3, transform: `scale(${0.8 + 0.2 * pop})`, opacity: pop }}>
        {title}
      </div>
      <div style={{ fontSize: 44, marginTop: 24, color: '#93c5fd', opacity: fade }}>{subtitle}</div>
    </AbsoluteFill>
  )
}
