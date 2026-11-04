// The face of an agent: a pixel-art character (pixels.ts) built from the 9 parts stored in its agent.json
// (avatar: {color, eyes, mouth, hat, bg, skin, head, hair, hair_color}). One <rect> per run of pixels on a 20x20
// grid with crisp edges, so it stays sharp from 14 px (session header) to 128 px. The colours are swatches the user
// picks (like the accent picker): the only hard-coded colours of the feature.
import type * as React from 'react'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'
import { GRID, normalize, pixelsOf, tileRuns, type Run } from './pixels'

export { AVATAR_OPTIONS, AVATAR_PARTS, DEFAULT_AVATAR, INK, SKIN, HAIR, SWATCH, projectColor, randomAvatar, type AvatarPart } from './pixels'

/** `sleep` = eyes closed (agent off); `animate` = blinks now and then (off under prefers-reduced-motion). */
export type AvatarMood = 'idle' | 'sleep'

type Props = {
  avatar?: Partial<AgentAvatar> | null
  size?: number
  className?: string
  title?: string
  /** false = the character alone, no background tile (standing in a scene) */
  tile?: boolean
  mood?: AvatarMood
  animate?: boolean
}

const Rects = ({ runs }: { runs: Run[] }) => (
  <>
    {runs.map((r) => (
      <rect key={`${r.x}.${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={r.fill} />
    ))}
  </>
)

export function AgentAvatarIcon({ avatar, size = 24, className, title, tile = true, mood = 'idle', animate = false }: Props) {
  const a = normalize(avatar)
  const px = pixelsOf(a, mood === 'sleep')
  const blink = animate && px.blink.length > 0
  // Each face blinks at its own moment (a stable delay from its parts), so a room never blinks at once.
  const delay = blink ? -([...Object.values(a).join('')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 997, 7) % 52) / 10 : 0
  return (
    <svg
      viewBox={`0 0 ${GRID} ${GRID}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      className={cn('shrink-0', blink && 'mx-px-blinker', className)}
      style={blink ? ({ '--mx-blink-delay': `${delay}s` } as React.CSSProperties) : undefined}
    >
      {title && <title>{title}</title>}
      {tile && <Rects runs={tileRuns(a.bg)} />}
      <Rects runs={px.body} />
      <g className="mx-px-eyes">
        <Rects runs={px.eyes} />
      </g>
      {blink && (
        <g className="mx-px-blink">
          <Rects runs={px.blink} />
        </g>
      )}
    </svg>
  )
}
