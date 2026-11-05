// The face of an agent: a pixel-art character (pixels.ts) built from the 6 parts stored in its agent.json
// (avatar: {color, skin, hair, hair_color, face, accessory}). One <rect> per run of pixels on a 16x16 grid with crisp
// edges: sharpest at multiples of 16 px (16 in a session header, 32 in lists, 64-96 on the Agents page). The tile
// behind it is a soft tint of its outfit colour (an accent colour of the UI), so it sits on light and dark themes.
import * as React from 'react'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'
import { AVATAR_PARTS, GRID, normalize, pixelsOf, type Run } from './pixels'

export { AVATAR_OPTIONS, AVATAR_PARTS, DEFAULT_AVATAR, HAIR, INK, OUTFIT, SKIN, projectColor, randomAvatar, type AvatarPart } from './pixels'

/** `sleep` = eyes closed and greyed (agent off). */
export type AvatarMood = 'idle' | 'sleep'

type Props = {
  avatar?: Partial<AgentAvatar> | null
  size?: number
  className?: string
  title?: string
  /** false = the character alone, no background tile (sitting at its desk) */
  tile?: boolean
  mood?: AvatarMood
  /** blinks now and then (off under prefers-reduced-motion) */
  animate?: boolean
}

// The runs come from pixelsOf's cache (same array for the same face), so a redraw of the page skips the rects.
const Rects = React.memo(({ runs }: { runs: Run[] }) => (
  <>
    {runs.map((r) => (
      <rect key={`${r.x}.${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={r.fill} />
    ))}
  </>
))

/** The tile: a rounded square (corners cut by one pixel). */
const TILE = `M1 0h${GRID - 2}v1h1v${GRID - 2}h-1v1h-${GRID - 2}v-1h-1v-${GRID - 2}h1z`

function AvatarIcon({ avatar, size = 32, className, title, tile = true, mood = 'idle', animate = false }: Props) {
  const a = normalize(avatar)
  const px = pixelsOf(a, mood === 'sleep')
  const blink = animate && px.blink.length > 0
  // Each face blinks at its own moment (a stable delay from its parts), so a page never blinks at once.
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
      {tile && <path d={TILE} fill={px.tile} fillOpacity={0.22} />}
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

/** Memoized on the 6 parts (a refetch hands a new avatar object with the same face): lists and the Office draw
 *  thousands of rects. */
export const AgentAvatarIcon = React.memo(AvatarIcon, (p, n) => {
  const { avatar: pa, ...pr } = p
  const { avatar: na, ...nr } = n
  const keys = new Set([...Object.keys(pr), ...Object.keys(nr)]) as Set<keyof typeof pr>
  for (const k of keys) if (pr[k] !== nr[k]) return false
  return pa === na || (!!pa && !!na && AVATAR_PARTS.every((k) => pa[k] === na[k]))
})
