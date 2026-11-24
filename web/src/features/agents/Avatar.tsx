// The face of an agent: a pixel-art character (pixels.ts) built from the 6 parts stored in its agent.json
// (avatar: {color, skin, hair, hair_color, face, accessory}). One <rect> per run of pixels on a 16x16 grid with crisp
// edges: sharpest at multiples of 16 px (16 in a session header, 32 in lists, 64-96 on the Agents page). The tile
// behind it is a soft tint of its outfit colour (an accent colour of the UI), so it sits on light and dark themes.
import * as React from 'react'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'
import { AVATAR_PARTS, GRID, normalize, pixelsOf, type Run } from './pixels'

export { AVATAR_OPTIONS, AVATAR_PARTS, DEFAULT_AVATAR, HAIR, OUTFIT, SKIN, projectColor, randomAvatar, type AvatarPart } from './pixels'

/** `sleep` = eyes closed and greyed (agent off); animated, it breathes slowly and "z z" float above it. */
type AvatarMood = 'idle' | 'sleep'

/** `tile` false = the character alone (sitting at its desk); `animate` = alive: breathes (head up and down one
 *  pixel), blinks now and then, looks left and right; asleep, slow breath and floating "z" (each face on its own beat;
 *  all off under reduced motion). On by default from 24 px: the 16 px faces of lists and chips stay still. */
type Props = { avatar?: Partial<AgentAvatar> | null; size?: number; className?: string; title?: string; tile?: boolean; mood?: AvatarMood; animate?: boolean; /** asleep and animated: the floating "z" (off where the page shows its own) */ zzz?: boolean }

// The runs come from pixelsOf's cache (same array for the same face), so a redraw of the page skips the rects.
const Rects = React.memo(({ runs }: { runs: Run[] }) => (
  <>{runs.map((r) => <rect key={`${r.x}.${r.y}`} x={r.x} y={r.y} width={r.w} height={1} fill={r.fill} />)}</>
))

/** The tile: a rounded square (corners cut by one pixel). */
const TILE = `M1 0h${GRID - 2}v1h1v${GRID - 2}h-1v1h-${GRID - 2}v-1h-1v-${GRID - 2}h1z`

/** A 4x4 pixel "z" at (x, y). */
const zPath = (x: number, y: number) => `M${x} ${y}h4v1h-4zM${x + 2} ${y + 1}h1v1h-1zM${x + 1} ${y + 2}h1v1h-1zM${x} ${y + 3}h4v1h-4z`

function AvatarIcon({ avatar, size = 32, className, title, tile = true, mood = 'idle', animate = size >= 24, zzz = true }: Props) {
  const a = normalize(avatar)
  const px = pixelsOf(a, mood === 'sleep')
  const blink = animate && mood !== 'sleep' && px.blink.length > 0
  // Each face blinks at its own moment (a stable delay from its parts), so a page never blinks at once.
  const delay = animate ? -([...Object.values(a).join('')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 997, 7) % 52) / 10 : 0
  return (
    <svg
      viewBox={`0 0 ${GRID} ${GRID}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      className={cn('shrink-0', blink && 'mx-px-blinker', className)}
      style={animate ? ({ '--mx-blink-delay': `${delay}s`, '--mx-look-l': `${-px.look[0]}px`, '--mx-look-r': `${px.look[1]}px` } as React.CSSProperties) : undefined}
    >
      {title && <title>{title}</title>}
      {tile && <path d={TILE} fill={px.tile} fillOpacity={0.22} />}
      {animate && mood === 'sleep' ? (
        <>
          <Rects runs={px.bust} />
          <g className="mx-px-snore">
            <Rects runs={px.head} />
            <Rects runs={px.eyes} />
          </g>
          {zzz && (
            <g fill="#5b9cf6">
              <path className="mx-px-z" d={zPath(12, 3)} />
              <path className="mx-px-z mx-px-z2" d={zPath(12, 3)} />
            </g>
          )}
        </>
      ) : animate ? (
        <>
          <Rects runs={px.bust} />
          <g className="mx-px-nod">
            <Rects runs={px.head} />
            <g className="mx-px-look">
              <g className="mx-px-eyes"><Rects runs={px.eyes} /></g>
            </g>
            {blink && <g className="mx-px-blink"><Rects runs={px.blink} /></g>}
          </g>
        </>
      ) : (
        <>
          <Rects runs={px.body} />
          <g className="mx-px-eyes"><Rects runs={px.eyes} /></g>
        </>
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
