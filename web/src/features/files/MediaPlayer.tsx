// Light video / audio player in the app's style (theme accent), no dependency.
// - video: poster (server thumbnail) shown at once, big play button, controls that fade out while playing;
// - progress bar with buffered range and hover time, drag to seek (mouse, touch, keyboard);
// - volume / mute, speed (0.5x-4x), picture-in-picture, fullscreen;
// - keys when focused: Space/K play, ←/→ ±5 s, J/L ±10 s, ↑/↓ volume, M mute, F fullscreen, 0-9 jump, </> speed.
// `preload="metadata"`: nothing but the header is downloaded before Play (Range requests on /raw).
// - video quality (videoQuality.ts): Auto / Original / lighter copies made by the server; switching keeps the time.
// Speed and quality are native <select>s under small buttons: the phone's own picker, never clipped by a small
// player, shown in full screen, and Escape closes them without closing the viewer around the player.
import * as React from 'react'
import { Gauge, Maximize, Minimize, Pause, PictureInPicture2, Play, RotateCcw, Volume1, Volume2, VolumeX } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Sensitive, Spinner, Tooltip } from '@/components/ui'
import { fileRawUrl, fileThumbUrl } from '@/lib/queries/files'
import { basename } from './kinds'
import { useVideoQuality, type VideoInfo } from './videoQuality'

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4]

function fmt(t: number) {
  if (!Number.isFinite(t) || t < 0) return '0:00'
  const s = Math.floor(t % 60)
  const m = Math.floor((t / 60) % 60)
  const h = Math.floor(t / 3600)
  return (h ? `${h}:${String(m).padStart(2, '0')}` : String(m)) + `:${String(s).padStart(2, '0')}`
}

/** `onOpen` (audio): the name opens the file viewer - the player shown inline in a conversation. */
export function MediaPlayer({ path, kind, version, onError, onOpen, className }: { path: string; kind: 'video' | 'audio'; version?: number | null; onError?: () => void; onOpen?: () => void; className?: string }) {
  const t = useT()
  const media = React.useRef<HTMLVideoElement & HTMLAudioElement>(null)
  const root = React.useRef<HTMLDivElement>(null)
  const bar = React.useRef<HTMLDivElement>(null)
  const [playing, setPlaying] = React.useState(false)
  const [started, setStarted] = React.useState(false)
  const [waiting, setWaiting] = React.useState(false)
  const [ended, setEnded] = React.useState(false)
  const [time, setTime] = React.useState(0)
  const [duration, setDuration] = React.useState(0)
  const [buffered, setBuffered] = React.useState(0)
  const [volume, setVolume] = React.useState(1)
  const [muted, setMuted] = React.useState(false)
  const [speed, setSpeed] = React.useState(1)
  const [fullscreen, setFullscreen] = React.useState(false)
  const [hover, setHover] = React.useState<{ x: number; t: number } | null>(null)
  const [idle, setIdle] = React.useState(false)
  const dragging = React.useRef(false)
  const idleTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const video = kind === 'video'

  // Auto makes its copy once the video is played, not for a video only opened to have a look.
  const vq = useVideoQuality(path, video, version, started)
  const [copyFailed, setCopyFailed] = React.useState(false)
  const copy = video && vq.src && !copyFailed ? vq.src : null
  const src = copy ?? fileRawUrl(path, false, version)
  // Switching source (another quality): resume at the same time, playing if it was.
  const resume = React.useRef<{ t: number; play: boolean } | null>(null)
  const last = React.useRef({ t: 0, play: false, src })
  if (last.current.src !== src) {
    resume.current = last.current.t > 0 || last.current.play ? { t: last.current.t, play: last.current.play } : null
    last.current.src = src
  }
  const poster = video ? fileThumbUrl(path, 1280, version) : undefined

  // Controls fade out after 2.5 s without moving while a video plays.
  const poke = React.useCallback(() => {
    setIdle(false)
    clearTimeout(idleTimer.current)
    idleTimer.current = setTimeout(() => setIdle(true), 2500)
  }, [])
  React.useEffect(() => () => clearTimeout(idleTimer.current), [])
  React.useEffect(() => {
    const onFs = () => setFullscreen(document.fullscreenElement === root.current)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  const el = () => media.current
  const toggle = () => {
    const m = el()
    if (!m) return
    if (m.paused || m.ended) {
      setStarted(true) // asked to play: the Auto copy may start (even when this browser cannot read the original)
      void m.play().catch(() => {})
    } else m.pause()
  }
  const seek = (to: number) => {
    const m = el()
    if (!m || !Number.isFinite(m.duration)) return
    m.currentTime = Math.max(0, Math.min(m.duration, to))
    setTime(m.currentTime)
  }
  const setVol = (v: number) => {
    const m = el()
    if (!m) return
    m.volume = Math.max(0, Math.min(1, v))
    m.muted = m.volume === 0
  }
  const setRate = (r: number) => {
    const m = el()
    if (m) m.playbackRate = r
  }
  /** One step up / down the speed list (keys > and <). */
  const stepSpeed = (dir: 1 | -1) => {
    const m = el()
    if (!m) return
    const next = dir > 0 ? SPEEDS.find((x) => x > m.playbackRate + 1e-3) : [...SPEEDS].reverse().find((x) => x < m.playbackRate - 1e-3)
    if (next) m.playbackRate = next
  }
  const toggleFullscreen = () => {
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => {})
    else if (root.current?.requestFullscreen) void root.current.requestFullscreen().catch(() => {})
    else (media.current as (HTMLVideoElement & { webkitEnterFullscreen?: () => void }) | null)?.webkitEnterFullscreen?.() // iPhone: only the video itself goes full screen
  }
  const pip = () => {
    const v = media.current as HTMLVideoElement | null
    if (!v) return
    if (document.pictureInPictureElement) void document.exitPictureInPicture().catch(() => {})
    else void v.requestPictureInPicture?.().catch(() => {})
  }

  const timeAt = (clientX: number) => {
    const r = bar.current?.getBoundingClientRect()
    if (!r || !duration) return 0
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration
  }
  const onBarDown = (e: React.PointerEvent) => {
    e.preventDefault()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    dragging.current = true
    seek(timeAt(e.clientX))
  }
  const onBarMove = (e: React.PointerEvent) => {
    const r = bar.current?.getBoundingClientRect()
    if (r) setHover({ x: Math.max(0, Math.min(r.width, e.clientX - r.left)), t: timeAt(e.clientX) })
    if (dragging.current) seek(timeAt(e.clientX))
  }
  const onBarUp = () => {
    dragging.current = false
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    if ((e.target as HTMLElement).tagName === 'SELECT') return      // the speed / quality picker has its own keys
    const k = e.key.toLowerCase()
    const m = el()
    if (!m) return
    let handled = true
    if (e.key === '>') stepSpeed(1)
    else if (e.key === '<') stepSpeed(-1)
    else if (k === ' ' || k === 'k') toggle()
    else if (k === 'arrowleft') seek(m.currentTime - 5)
    else if (k === 'arrowright') seek(m.currentTime + 5)
    else if (k === 'j') seek(m.currentTime - 10)
    else if (k === 'l') seek(m.currentTime + 10)
    else if (k === 'arrowup') setVol(m.volume + 0.1)
    else if (k === 'arrowdown') setVol(m.volume - 0.1)
    else if (k === 'm') m.muted = !m.muted
    else if (k === 'f' && video) toggleFullscreen()
    else if (/^[0-9]$/.test(k)) seek((Number(k) / 10) * (m.duration || 0))
    else handled = false
    if (handled) {
      e.preventDefault()
      e.stopPropagation()
      poke()
    }
  }

  const pct = duration ? (time / duration) * 100 : 0
  const showControls = !video || !playing || !idle || dragging.current
  const VolIcon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2

  const controls = (
    <div className={cn('flex flex-col gap-1.5', video ? 'px-3 pt-8 pb-2.5 text-white [background:linear-gradient(to_top,rgb(0_0_0/0.72),transparent)]' : 'text-foreground')}>
      {/* progress */}
      <div
        ref={bar}
        role="slider"
        tabIndex={-1}
        aria-label={t('media.seek')}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(time)}
        aria-valuetext={`${fmt(time)} / ${fmt(duration)}`}
        onPointerDown={onBarDown}
        onPointerMove={onBarMove}
        onPointerUp={onBarUp}
        onPointerCancel={onBarUp}
        onPointerLeave={() => setHover(null)}
        className="group/bar relative flex h-4 cursor-pointer max-md:h-8 pointer-coarse:h-8 touch-none items-center"
      >
        <div className={cn('relative h-1 w-full overflow-hidden rounded-full transition-[height] group-hover/bar:h-1.5', video ? 'bg-white/25' : 'bg-muted')}>
          <div className={cn('absolute inset-y-0 left-0', video ? 'bg-white/35' : 'bg-foreground/15')} style={{ width: `${duration ? (buffered / duration) * 100 : 0}%` }} />
          <div className="absolute inset-y-0 left-0 bg-primary" style={{ width: `${pct}%` }} />
        </div>
        <div className="pointer-events-none absolute size-3 -translate-x-1/2 rounded-full bg-primary shadow ring-2 ring-white/80 transition-transform group-hover/bar:scale-110" style={{ left: `${pct}%` }} />
        {hover && duration > 0 && (
          <div className="pointer-events-none absolute -top-7 -translate-x-1/2 rounded-md bg-popover px-1.5 py-0.5 text-[11px] font-medium text-popover-foreground tabular-nums shadow-pop" style={{ left: hover.x }}>
            {fmt(hover.t)}
          </div>
        )}
      </div>
      {/* buttons */}
      <div className="flex items-center gap-1">
        <CtrlButton label={playing ? t('media.pause') : ended ? t('media.replay') : t('media.play')} onClick={toggle} video={video}>
          {playing ? <Pause className="size-[18px] fill-current" /> : ended ? <RotateCcw className="size-[18px]" /> : <Play className="size-[18px] fill-current" />}
        </CtrlButton>
        <div className="group/vol flex items-center">
          <CtrlButton label={muted ? t('media.unmute') : t('media.mute')} onClick={() => el() && (el()!.muted = !el()!.muted)} video={video}>
            <VolIcon className="size-[18px]" />
          </CtrlButton>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            onChange={(e) => setVol(Number(e.target.value))}
            aria-label={t('media.volume')}
            className="h-1 w-0 cursor-pointer accent-[var(--primary)] opacity-0 transition-all group-focus-within/vol:w-20 group-focus-within/vol:opacity-100 group-hover/vol:w-20 group-hover/vol:opacity-100 max-md:hidden"
          />
        </div>
        <span className={cn('ml-1 text-xs tabular-nums', video ? 'text-white/90' : 'text-muted-foreground')}>
          {fmt(time)} <span className="opacity-60">/ {fmt(duration)}</span>
        </span>
        <span className="flex-1" />
        {video && !!vq.info?.qualities.length && (
          <PickButton
            label={t('media.quality')}
            testid="quality"
            value={String(vq.choice)}
            options={qualityOptions(vq.info, t)}
            onPick={(v) => {
              vq.setChoice(v === 'auto' || v === 'original' ? v : Number(v))
              setCopyFailed(false)
            }}
            video={video}
          >
            <span className="relative text-xs font-semibold tabular-nums">
              {copy ? `${vq.playing}p` : vq.choice === 'auto' ? 'Auto' : `${vq.info.height}p`}
              {(vq.targetState?.state === 'queued' || vq.targetState?.state === 'running') && <span className="absolute -top-0.5 -right-1.5 size-1.5 animate-pulse rounded-full bg-primary" />}
            </span>
          </PickButton>
        )}
        <PickButton
          label={t('media.speed')}
          testid="speed"
          value={String(speed)}
          options={SPEEDS.map((r) => ({ value: String(r), label: r === 1 ? t('media.speedNormal') : `${r}×` }))}
          onPick={(v) => setRate(Number(v))}
          video={video}
        >
          {speed === 1 ? <Gauge className="size-[18px]" /> : <span className="text-xs font-semibold tabular-nums">{speed}×</span>}
        </PickButton>
        {video && typeof document !== 'undefined' && 'pictureInPictureEnabled' in document && (
          <CtrlButton label={t('media.pip')} onClick={pip} video={video}>
            <PictureInPicture2 className="size-[18px]" />
          </CtrlButton>
        )}
        {video && (
          <CtrlButton label={fullscreen ? t('media.exitFullscreen') : t('media.fullscreen')} onClick={toggleFullscreen} video={video}>
            {fullscreen ? <Minimize className="size-[18px]" /> : <Maximize className="size-[18px]" />}
          </CtrlButton>
        )}
      </div>
    </div>
  )

  const events = {
    onPlay: () => {
      last.current.play = true
      setPlaying(true)
      setStarted(true)
      setEnded(false)
      poke()
    },
    onPause: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      // A source switch pauses on its own: that pause must not stop the playback that resumes after it.
      if (!e.currentTarget.ended && e.currentTarget.currentTime === 0 && resume.current) return
      last.current.play = false
      setPlaying(false)
    },
    onEnded: () => {
      setPlaying(false)
      setEnded(true)
    },
    onWaiting: () => setWaiting(true),
    onPlaying: () => setWaiting(false),
    onCanPlay: () => setWaiting(false),
    onTimeUpdate: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      last.current.t = e.currentTarget.currentTime
      if (!dragging.current) setTime(e.currentTarget.currentTime)
    },
    onLoadedMetadata: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      const m = e.currentTarget
      setDuration(m.duration)
      const r = resume.current
      resume.current = null
      if (r) {
        m.currentTime = Math.min(r.t, m.duration || r.t)
        m.playbackRate = speed
        if (r.play) void m.play().catch(() => {})
      }
    },
    onDurationChange: (e: React.SyntheticEvent<HTMLMediaElement>) => setDuration(e.currentTarget.duration),
    onProgress: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      const b = e.currentTarget.buffered
      const now = e.currentTarget.currentTime
      for (let i = 0; i < b.length; i++) if (b.start(i) <= now + 0.5) setBuffered(b.end(i))
    },
    onVolumeChange: (e: React.SyntheticEvent<HTMLMediaElement>) => {
      setVolume(e.currentTarget.volume)
      setMuted(e.currentTarget.muted)
    },
    onRateChange: (e: React.SyntheticEvent<HTMLMediaElement>) => setSpeed(e.currentTarget.playbackRate),
    onError: () => {
      if (copy) return setCopyFailed(true)
      setStarted(true) // an original this browser cannot read (HEVC, ProRes): the Auto copy is the way to play it
      onError?.()
    },
  }

  if (!video)
    return (
      <div className={cn('relative grid w-full max-w-lg gap-3 rounded-xl border bg-card p-4 shadow-xs outline-none focus-visible:ring-2 focus-visible:ring-ring', className)} tabIndex={0} onKeyDown={onKey} data-media-player>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={toggle}
            aria-label={playing ? t('media.pause') : t('media.play')}
            className="flex size-11 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-xs transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
          >
            {waiting && playing ? <Spinner className="size-5" /> : playing ? <Pause className="size-5 fill-current" /> : <Play className="ml-0.5 size-5 fill-current" />}
          </button>
          {onOpen ? (
            <button type="button" onClick={onOpen} title={t('media.open')} className="min-w-0 flex-1 truncate rounded-sm text-left text-sm font-medium outline-none hover:underline focus-visible:ring-2 focus-visible:ring-ring">
              <Sensitive length={8}>{basename(path)}</Sensitive>
            </button>
          ) : (
            <p className="min-w-0 flex-1 truncate text-sm font-medium">
              <Sensitive length={8}>{basename(path)}</Sensitive>
            </p>
          )}
        </div>
        {controls}
        <audio ref={media} key={path} src={src} preload="metadata" className="hidden" {...events} />
      </div>
    )

  return (
    <div
      ref={root}
      tabIndex={0}
      onKeyDown={onKey}
      data-media-player
      onPointerMove={poke}
      className={cn(
        'group/player relative flex max-h-full max-w-full overflow-hidden rounded-xl bg-black shadow-pop outline-none focus-visible:ring-2 focus-visible:ring-ring',
        fullscreen && 'rounded-none',
        playing && idle && 'cursor-none',
        className,
      )}
    >
      <video
        ref={media}
        key={path}
        src={src}
        poster={poster}
        preload="metadata"
        playsInline
        onClick={toggle}
        onDoubleClick={toggleFullscreen}
        className="max-h-[inherit] w-full max-w-full object-contain"
        {...events}
      />
      {/* centre: big play / spinner */}
      {(!playing || (waiting && started)) && (
        <button
          type="button"
          onClick={toggle}
          aria-label={ended ? t('media.replay') : t('media.play')}
          className="absolute inset-0 m-auto flex size-16 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-pop transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none"
        >
          {waiting && started ? <Spinner className="size-7" /> : ended ? <RotateCcw className="size-7" /> : <Play className="ml-1 size-7 fill-current" />}
        </button>
      )}
      <div className={cn('absolute inset-x-0 bottom-0 transition-opacity duration-300', showControls ? 'opacity-100' : 'pointer-events-none opacity-0')}>{controls}</div>
    </div>
  )
}

function CtrlButton({ label, onClick, video, children }: { label: string; onClick: () => void; video: boolean; children: React.ReactNode }) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className={cn(
          'flex size-8 items-center justify-center rounded-md transition-colors max-md:size-10 pointer-coarse:size-10 focus-visible:ring-2 focus-visible:outline-none',
          video ? 'text-white/90 hover:bg-white/15 hover:text-white focus-visible:ring-white/70' : 'text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring',
        )}
      >
        {children}
      </button>
    </Tooltip>
  )
}

/** A control that opens a native list (speed, quality): an invisible <select> over the button. */
function PickButton({ label, testid, value, options, onPick, video, children }: { label: string; testid: string; value: string; options: { value: string; label: string }[]; onPick: (v: string) => void; video: boolean; children: React.ReactNode }) {
  return (
    <Tooltip content={label}>
      <span
        data-testid={`${testid}-button`}
        className={cn(
          'relative flex h-8 min-w-8 items-center max-md:h-10 max-md:min-w-10 pointer-coarse:h-10 pointer-coarse:min-w-10 justify-center rounded-md px-1 transition-colors has-[select:focus-visible]:ring-2',
          video ? 'text-white/90 hover:bg-white/15 hover:text-white has-[select:focus-visible]:ring-white/70' : 'text-muted-foreground hover:bg-accent hover:text-foreground has-[select:focus-visible]:ring-ring',
        )}
      >
        {children}
        <select
          aria-label={label}
          data-testid={`${testid}-select`}
          value={value}
          onChange={(e) => onPick(e.target.value)}
          // The list a computer opens takes the select's colors: without its own, it inherits the player's white text
          // and shows white options on a white list (only the highlighted one was readable).
          className="absolute inset-0 cursor-pointer appearance-none bg-popover text-popover-foreground opacity-0"
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} className="bg-popover text-popover-foreground">
              {o.label}
            </option>
          ))}
        </select>
      </span>
    </Tooltip>
  )
}

function qualityOptions(info: VideoInfo, t: ReturnType<typeof useT>): { value: string; label: string }[] {
  const mbps = info.bitrate ? ` · ${(info.bitrate / 1e6).toFixed(info.bitrate < 1e7 ? 1 : 0)} Mb/s` : ''
  const state = (q: VideoInfo['qualities'][number]) =>
    q.state === 'running' ? ` · ${Math.round(q.progress * 100)} %` : q.state === 'queued' ? ` · ${t('media.qualityQueued')}` : q.state === 'error' ? ` · ${t('media.qualityFailed')}` : ''
  return [
    { value: 'auto', label: `${t('media.qualityAuto')} (${info.auto ? `${info.auto}p` : t('media.qualityOriginal')})` },
    { value: 'original', label: `${t('media.qualityOriginal')} · ${info.height}p${mbps}` },
    ...info.qualities.map((q) => ({ value: String(q.q), label: `${q.q}p${state(q)}` })),
  ]
}
