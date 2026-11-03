// The face of an agent: a small character drawn in SVG from 5 options stored in its agent.json
// (avatar: {color, eyes, mouth, hat, bg}). Readable from 16 px (sessions tree) to 96 px (agent page), light and dark.
// The colours are swatches the user picks (like the accent picker): the only hard-coded colours of the feature.
import { useId } from 'react'
import { cn } from '@/lib/utils'
import type { AgentAvatar } from '@/lib/types'

export const AVATAR_OPTIONS = {
  color: ['violet', 'blue', 'teal', 'green', 'amber', 'orange', 'rose', 'slate'],
  eyes: ['dots', 'happy', 'wide', 'sleepy', 'wink', 'visor'],
  mouth: ['smile', 'grin', 'flat', 'open', 'smirk'],
  hat: ['none', 'antenna', 'cap', 'beanie', 'crown', 'headphones', 'wizard'],
  bg: ['violet', 'blue', 'teal', 'green', 'amber', 'orange', 'rose', 'slate'],
} as const
export type AvatarPart = keyof typeof AVATAR_OPTIONS
export const AVATAR_PARTS: AvatarPart[] = ['color', 'eyes', 'mouth', 'hat', 'bg']
export const DEFAULT_AVATAR: AgentAvatar = { color: 'violet', eyes: 'dots', mouth: 'smile', hat: 'antenna', bg: 'slate' }

/** body, shade (darker edge), accessory (a contrasting colour for hats) */
export const SWATCH: Record<string, { body: string; shade: string; acc: string }> = {
  violet: { body: '#8b5cf6', shade: '#6d28d9', acc: '#f59e0b' },
  blue: { body: '#3b82f6', shade: '#1d4ed8', acc: '#f59e0b' },
  teal: { body: '#14b8a6', shade: '#0f766e', acc: '#f43f5e' },
  green: { body: '#22c55e', shade: '#15803d', acc: '#8b5cf6' },
  amber: { body: '#f59e0b', shade: '#b45309', acc: '#3b82f6' },
  orange: { body: '#f97316', shade: '#c2410c', acc: '#14b8a6' },
  rose: { body: '#f43f5e', shade: '#be123c', acc: '#14b8a6' },
  slate: { body: '#64748b', shade: '#334155', acc: '#f59e0b' },
}
const INK = '#1c1a29'
const GOLD = '#facc15'

const pick = <K extends AvatarPart>(part: K, v: string | undefined): string =>
  (AVATAR_OPTIONS[part] as readonly string[]).includes(v || '') ? v! : DEFAULT_AVATAR[part]

export function randomAvatar(): AgentAvatar {
  const r = <K extends AvatarPart>(k: K) => AVATAR_OPTIONS[k][Math.floor(Math.random() * AVATAR_OPTIONS[k].length)]
  const color = r('color')
  let bg: string = r('bg')
  if (bg === color) bg = AVATAR_OPTIONS.bg[(AVATAR_OPTIONS.bg.indexOf(bg as never) + 3) % AVATAR_OPTIONS.bg.length]
  return { color, eyes: r('eyes'), mouth: r('mouth'), hat: r('hat'), bg }
}

type Props = { avatar?: Partial<AgentAvatar> | null; size?: number; className?: string; title?: string }

export function AgentAvatarIcon({ avatar, size = 24, className, title }: Props) {
  const clip = useId()
  const a = {
    color: pick('color', avatar?.color),
    eyes: pick('eyes', avatar?.eyes),
    mouth: pick('mouth', avatar?.mouth),
    hat: pick('hat', avatar?.hat),
    bg: pick('bg', avatar?.bg),
  }
  const c = SWATCH[a.color]
  const bg = SWATCH[a.bg]
  const small = size <= 22
  // Strokes and dots grow when the avatar is tiny, so the face still reads at 16 px.
  const sw = small ? 2.9 : 2.1
  const dot = small ? 2.6 : 2.2
  const ink = { stroke: INK, strokeWidth: sw, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, fill: 'none' }
  return (
    <svg
      viewBox="0 0 40 40"
      width={size}
      height={size}
      role={title ? 'img' : undefined}
      aria-hidden={title ? undefined : true}
      className={cn('shrink-0', className)}
    >
      {title && <title>{title}</title>}
      <defs>
        <clipPath id={clip}>
          <rect width="40" height="40" rx="11" />
        </clipPath>
      </defs>
      <g clipPath={`url(#${clip})`}>
        <rect width="40" height="40" fill={bg.body} fillOpacity={0.3} />
        <rect width="40" height="40" fill={bg.body} fillOpacity={0.18} y={30} />
        {/* back of the hat (behind the head) */}
        {a.hat === 'headphones' && <path d="M8.5 22 Q8.5 9 20 9 Q31.5 9 31.5 22" stroke={c.acc} strokeWidth={small ? 3.4 : 2.6} fill="none" strokeLinecap="round" />}
        {a.hat === 'antenna' && (
          <>
            <path d="M20 13 V6.5" stroke={c.shade} strokeWidth={small ? 2.8 : 2} strokeLinecap="round" />
            <circle cx="20" cy="5.5" r={small ? 3 : 2.5} fill={c.acc} />
          </>
        )}
        {/* body */}
        <rect x="7.5" y="11.5" width="25" height="22" rx="9.5" fill={c.body} />
        <rect x="7.5" y="11.5" width="25" height="22" rx="9.5" fill="none" stroke={c.shade} strokeOpacity={0.55} strokeWidth="1.2" />
        <rect x="12" y="35" width="16" height="8" rx="4" fill={c.shade} />
        {!small && <ellipse cx="13.5" cy="15.5" rx="2.6" ry="1.4" fill="#fff" fillOpacity={0.35} />}
        {/* cheeks */}
        {!small && (
          <>
            <circle cx="11.8" cy="26.2" r="1.9" fill="#fb7185" fillOpacity={0.45} />
            <circle cx="28.2" cy="26.2" r="1.9" fill="#fb7185" fillOpacity={0.45} />
          </>
        )}
        <Eyes kind={a.eyes} dot={dot} ink={ink} small={small} />
        <Mouth kind={a.mouth} ink={ink} small={small} />
        {/* front of the hat */}
        {a.hat === 'headphones' && (
          <>
            <rect x="4.6" y="18" width="5.6" height="9" rx="2.6" fill={c.acc} />
            <rect x="29.8" y="18" width="5.6" height="9" rx="2.6" fill={c.acc} />
          </>
        )}
        {a.hat === 'cap' && (
          <>
            <path d="M8.6 15.5 Q8.6 7 20 7 Q31.4 7 31.4 15.5 Z" fill={c.acc} />
            <path d="M20 15.5 H35 Q35.6 15.5 35.2 16.6 Q34.6 18 33 18 H20 Z" fill={c.acc} />
            <path d="M8.6 15.5 H31.4" stroke={INK} strokeOpacity={0.25} strokeWidth="1.2" />
            {!small && <circle cx="20" cy="7.6" r="1.2" fill={INK} fillOpacity={0.3} />}
          </>
        )}
        {a.hat === 'beanie' && (
          <>
            <path d="M8.2 16 Q8.2 6.5 20 6.5 Q31.8 6.5 31.8 16 Z" fill={c.acc} />
            <rect x="7.2" y="13.4" width="25.6" height="4" rx="2" fill={c.acc} />
            <rect x="7.2" y="13.4" width="25.6" height="4" rx="2" fill={INK} fillOpacity={0.15} />
            <circle cx="20" cy="5.6" r={small ? 3.2 : 2.6} fill={c.acc} />
          </>
        )}
        {a.hat === 'crown' && <path d="M11.5 14 L11 6.5 L15.6 10 L20 4.5 L24.4 10 L29 6.5 L28.5 14 Z" fill={GOLD} stroke="#ca8a04" strokeWidth="1" strokeLinejoin="round" />}
        {a.hat === 'wizard' && (
          <>
            <path d="M11 14.2 L20.5 1.2 L29 14.2 Z" fill={c.acc} />
            <ellipse cx="20" cy="14" rx="13" ry="2.4" fill={c.acc} />
            <ellipse cx="20" cy="14" rx="13" ry="2.4" fill={INK} fillOpacity={0.15} />
            {!small && <path d="M19.5 6.5 l0.9 1.8 2 0.3 -1.45 1.4 0.35 2 -1.8 -0.95 -1.8 0.95 0.35 -2 -1.45 -1.4 2 -0.3 Z" fill={GOLD} />}
          </>
        )}
      </g>
    </svg>
  )
}

type InkProps = { stroke: string; strokeWidth: number; strokeLinecap: 'round'; strokeLinejoin: 'round'; fill: string }

function Eyes({ kind, dot, ink, small }: { kind: string; dot: number; ink: InkProps; small: boolean }) {
  const L = 15
  const R = 25
  const y = 21.5
  const arc = (x: number, up: boolean) => <path d={up ? `M${x - 2.4} ${y + 1} Q${x} ${y - 2.6} ${x + 2.4} ${y + 1}` : `M${x - 2.4} ${y} Q${x} ${y + 2.2} ${x + 2.4} ${y}`} {...ink} />
  switch (kind) {
    case 'happy':
      return <>{arc(L, true)}{arc(R, true)}</>
    case 'sleepy':
      return <>{arc(L, false)}{arc(R, false)}</>
    case 'wink':
      return (
        <>
          <circle cx={L} cy={y} r={dot} fill={INK} />
          {arc(R, true)}
        </>
      )
    case 'wide':
      return (
        <>
          <circle cx={L} cy={y} r={small ? 3.6 : 3.3} fill="#fff" />
          <circle cx={R} cy={y} r={small ? 3.6 : 3.3} fill="#fff" />
          <circle cx={L + 0.5} cy={y + 0.3} r={small ? 2 : 1.7} fill={INK} />
          <circle cx={R + 0.5} cy={y + 0.3} r={small ? 2 : 1.7} fill={INK} />
        </>
      )
    case 'visor':
      return (
        <>
          <rect x="10.5" y={y - 3.2} width="19" height="6.4" rx="3.2" fill={INK} />
          <circle cx={L} cy={y} r={small ? 1.6 : 1.3} fill="#67e8f9" />
          <circle cx={R} cy={y} r={small ? 1.6 : 1.3} fill="#67e8f9" />
        </>
      )
    default: // dots
      return (
        <>
          <circle cx={L} cy={y} r={dot} fill={INK} />
          <circle cx={R} cy={y} r={dot} fill={INK} />
          {!small && <circle cx={L + 0.8} cy={y - 0.8} r="0.7" fill="#fff" />}
          {!small && <circle cx={R + 0.8} cy={y - 0.8} r="0.7" fill="#fff" />}
        </>
      )
  }
}

function Mouth({ kind, ink, small }: { kind: string; ink: InkProps; small: boolean }) {
  const y = 27.4
  switch (kind) {
    case 'grin':
      return <path d={`M16 ${y - 0.8} H24 Q24 ${y + 4} 20 ${y + 4} Q16 ${y + 4} 16 ${y - 0.8} Z`} fill={INK} stroke={INK} strokeWidth={small ? 1.2 : 0.8} strokeLinejoin="round" />
    case 'flat':
      return <path d={`M17 ${y + 0.4} H23`} {...ink} />
    case 'open':
      return <ellipse cx="20" cy={y + 0.6} rx={small ? 2.3 : 1.9} ry={small ? 2.6 : 2.3} fill={INK} />
    case 'smirk':
      return <path d={`M16.8 ${y + 0.8} Q20.5 ${y + 2.4} 23.4 ${y - 1}`} {...ink} />
    default: // smile
      return <path d={`M16.6 ${y - 0.4} Q20 ${y + 3.4} 23.4 ${y - 0.4}`} {...ink} />
  }
}
