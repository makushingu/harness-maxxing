// Light video / audio player in the app's style (theme accent), no dependency.
// - video: a black box of the video's shape from the start (size from /api/files/video, then from the file: no
//   300x150 frame, no jump), the poster (server thumbnail) at once, big play button, controls that fade out while
//   playing; on a touch screen a first tap on the picture shows the controls, a tap while they show plays / pauses;
// - progress bar with buffered range and hover time, drag to seek (mouse, touch, keyboard; one seek per 150 ms
//   while dragging, the position shown at once);
// - volume / mute, speed (0.5x-4x), picture-in-picture, fullscreen; on a touch screen the volume button opens the
//   slider (a second tap mutes); where the browser ignores `volume` (iPhone, iPad) the slider drives a Web Audio gain;
// - volume, mute and speed are kept in this browser, and where each file was left (mediaMemory.ts): opening it again
//   resumes there, with a "From start" chip until Play;
// - keys when focused: Space/K play, ←/→ ±5 s, J/L ±10 s, ↑/↓ volume, M mute, F fullscreen, 0-9 jump, </> speed
//   (on the volume slider the arrows move the volume);
// `preload="metadata"`: nothing but the header is downloaded before Play (Range requests on /raw).
// - video quality (videoQuality.ts): Auto / Original / lighter copies made by the server; switching keeps the time.
// - the source is frozen once playback started: a newer version of the file shows "File changed - Reload" instead of
//   switching under the viewer, and Auto changes source only when paused (or at once when the original fails or
//   struggles, or a quality is picked);
// - a lost connection (server restart, network) keeps the player: "Connection lost, resuming…", the same source is
//   loaded again at the same time (3 tries, then a Retry button and a quiet check every 5 s; again at once when the
//   tab shows or the network is back).
//   Only a file this browser cannot decode, with no copy possible, ends in the info card (`onError`);
// - a short clip without sound plays like a GIF: muted, looped, controls on hover / tap, no resume;
// - `keepAlive` (audio in a conversation): the element lives outside React (sharedAudio.ts), so playback goes on
//   when the message leaves the screen.
// Speed and quality are native <select>s under small buttons: the phone's own picker, never clipped by a small
// player, shown in full screen, and Escape closes them without closing the viewer around the player.
import * as React from 'react'
import { useQuery } from '@tanstack/react-query'
import { Gauge, Maximize, Minimize, Pause, PictureInPicture2, Play, RotateCcw, Volume1, Volume2, VolumeX } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useT } from '@/i18n'
import { Sensitive, Spinner, Tooltip } from '@/components/ui'
import { fileRawUrl, fileThumbUrl } from '@/lib/queries/files'
import { basename } from './kinds'
import { canDecode, gifLike, shownSize, useVideoQuality, videoInfoQuery, type VideoInfo } from './videoQuality'
import { clearMediaPos, mediaPosKey, readPrefs, resumePos, savePrefs, setMediaPos } from './mediaMemory'
import { releaseAudio, takeAudio } from './sharedAudio'

const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2, 2.5, 3, 4]

/** iPhone / iPad: `volume` is read-only (always 1, the hardware buttons rule). */
let volumeWorks: boolean | null = null
function canSetVolume() {
  if (volumeWorks == null) {
    const a = document.createElement('audio')
    try {
      a.volume = 0.5
    } catch {
      /* read-only */
    }
    volumeWorks = Math.abs(a.volume - 0.5) < 0.01
  }
  return volumeWorks
}
/** Where `volume` is read-only: the element's sound goes through a gain node, made on the first slider move only
 *  (an untouched player keeps the plain media path). One per element: an element can be routed only once. */
let audioCtx: AudioContext | null = null
const gains = new WeakMap<HTMLMediaElement, GainNode>()
function gainFor(m: HTMLMediaElement): GainNode | null {
  try {
    let g = gains.get(m)
    if (!g) {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext
      if (!Ctx) return null
      audioCtx ??= new Ctx()
      g = audioCtx.createGain()
      audioCtx.createMediaElementSource(m).connect(g).connect(audioCtx.destination)
      gains.set(m, g)
    }
    if (audioCtx?.state === 'suspended') void audioCtx.resume().catch(() => {})
    return g
  } catch {
    return null
  }
}

function fmt(t: number) {
  if (!Number.isFinite(t) || t < 0) return '0:00'
  const s = Math.floor(t % 60)
  const m = Math.floor((t / 60) % 60)
  const h = Math.floor(t / 3600)
  return (h ? `${h}:${String(m).padStart(2, '0')}` : String(m)) + `:${String(s).padStart(2, '0')}`
}

/** After a media error: is the server answering for this URL? 'down' = no answer, 401 or 5xx (a restart, the
 *  network); 'missing' = 403 / 404 (a copy removed from the cache, a file deleted); 'ok' = it serves the bytes, so
 *  the browser cannot decode them. */
async function reach(url: string): Promise<'ok' | 'down' | 'missing'> {
  try {
    const r = await fetch(url, { headers: { Range: 'bytes=0-0' }, cache: 'no-store', credentials: 'same-origin' })
    void r.body?.cancel().catch(() => {})
    if (r.ok) return 'ok'
    return r.status === 403 || r.status === 404 || r.status === 410 || r.status === 415 ? 'missing' : 'down'
  } catch {
    return 'down'
  }
}

const RETRY_MS = [1000, 3000, 6000]
const SEEK_EVERY_MS = 150
const MEDIA_EVENTS = [
  'play', 'pause', 'ended', 'waiting', 'playing', 'canplay', 'timeupdate', 'loadedmetadata', 'durationchange', 'progress',
  'volumechange', 'ratechange', 'error', 'webkitbeginfullscreen', 'webkitendfullscreen',
] as const
type MediaHandlers = Partial<Record<(typeof MEDIA_EVENTS)[number], (m: HTMLMediaElement) => void>>

/** Listeners on the element (also one React does not render: the shared audio), always calling the latest handlers;
 *  attached in a layout effect, before the element's first event can fire. */
function useMediaEvents(el: HTMLMediaElement | null, handlers: MediaHandlers) {
  const ref = React.useRef(handlers)
  React.useLayoutEffect(() => {
    ref.current = handlers
  })
  React.useLayoutEffect(() => {
    if (!el) return
    const fns = MEDIA_EVENTS.map((n) => [n, () => ref.current[n]?.(el)] as const)
    for (const [n, f] of fns) el.addEventListener(n, f)
    return () => {
      for (const [n, f] of fns) el.removeEventListener(n, f)
    }
  }, [el])
}

/** `onOpen` (audio): the name opens the file viewer - the player shown inline in a conversation. `keepAlive`
 *  (audio): playback goes on when the player unmounts (see sharedAudio.ts). */
export function MediaPlayer({ path, kind, version, onError, onOpen, keepAlive, className }: { path: string; kind: 'video' | 'audio'; version?: number | null; onError?: () => void; onOpen?: () => void; keepAlive?: boolean; className?: string }) {
  const t = useT()
  const media = React.useRef<HTMLMediaElement | null>(null)
  const [el, setEl] = React.useState<HTMLMediaElement | null>(null)
  const root = React.useRef<HTMLDivElement>(null)
  const bar = React.useRef<HTMLDivElement>(null)
  const prefs = React.useMemo(readPrefs, [])
  const [playing, setPlaying] = React.useState(false)
  const [started, setStarted] = React.useState(false)
  const [waiting, setWaiting] = React.useState(false)
  const [ended, setEnded] = React.useState(false)
  const [time, setTime] = React.useState(0)
  const [duration, setDuration] = React.useState(0)
  const [buffered, setBuffered] = React.useState(0)
  const [volume, setVolume] = React.useState(prefs.volume)
  const [muted, setMuted] = React.useState(prefs.muted)
  // touch screens: the volume button opens the slider (no hover there), closed again after a few seconds
  const [volOpen, setVolOpen] = React.useState(false)
  const volTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const gainVol = React.useRef<number | null>(null)
  const [speed, setSpeed] = React.useState(prefs.speed)
  const [fullscreen, setFullscreen] = React.useState(false)
  const [hover, setHover] = React.useState<{ x: number; t: number } | null>(null)
  const [idle, setIdle] = React.useState(false)
  const [dragT, setDragT] = React.useState<number | null>(null) // the bar is being dragged: the time shown
  const idleTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const controlsAtDown = React.useRef({ shown: true, touch: false }) // a tap on the picture: were the controls shown?
  const video = kind === 'video'
  const shared = !video && !!keepAlive

  // ---- source: original or a lighter copy (videoQuality.ts)
  const [rough, setRough] = React.useState(false) // the original struggles (long buffering, many dropped frames)
  const [origFailed, setOrigFailed] = React.useState(false) // the browser could not decode the original
  const [copyFailed, setCopyFailed] = React.useState(false)
  const copyRetries = React.useRef(0)
  const info = useQuery({ ...videoInfoQuery(path), enabled: video }).data // the query useVideoQuality runs too
  const decodable = video ? canDecode(info, path) : true
  const origBad = decodable === false || origFailed
  // Auto makes its copy once the video is played, not for a video only opened to have a look.
  const vq = useVideoQuality(path, video, version, started, origBad || rough, origBad)
  const gif = video && gifLike(info)
  React.useEffect(() => {
    if (gif) setIdle(true) // a GIF-like clip: controls only on hover / tap
  }, [gif])
  const copy = video && vq.src && !copyFailed ? vq.src : null
  const wanted = copy ?? fileRawUrl(path, false, version)
  // The source is frozen once playback started (see the header). `ver` = the file version it plays.
  const [cur, setCur] = React.useState({ src: wanted, ver: version ?? null })
  const src = cur.src
  const [changed, setChanged] = React.useState(false)
  const picked = React.useRef(false) // the user picked a quality: switch at once
  const played = React.useRef(false)
  React.useEffect(() => {
    if (wanted === cur.src) return setChanged(false)
    const m = media.current
    if (!started) return setCur({ src: wanted, ver: version ?? null })
    if (version && cur.ver && version !== cur.ver) return setChanged(true) // rewritten on disk: the user decides
    // at once: a quality the user picks (now or before: its copy is back), the original struggling, nothing playing
    if (picked.current || typeof vq.choice === 'number' || rough || !m || m.paused || m.ended || m.error) {
      picked.current = false
      setCur({ src: wanted, ver: version ?? cur.ver })
    }
  }, [wanted, cur, started, version, rough, playing, vq.choice])
  const reloadChanged = () => {
    setChanged(false)
    setCur({ src: wanted, ver: version ?? null })
  }
  const onCopy = !!copy && src === copy
  // Switching source (another quality, a reload): resume at the same time, playing if it was.
  const resume = React.useRef<{ t: number; play: boolean } | null>(null)
  const last = React.useRef({ t: 0, play: false, src })
  if (last.current.src !== src) {
    resume.current = last.current.t > 0 || last.current.play ? { t: last.current.t, play: last.current.play } : null
    last.current.src = src
  }
  const poster = video ? fileThumbUrl(path, 1280, version) : undefined
  // The copy came back (made again after it was removed from the cache): try it again.
  const copyState = vq.targetState?.state
  const prevCopyState = React.useRef(copyState)
  React.useEffect(() => {
    if (copyState === 'ready' && prevCopyState.current !== 'ready') setCopyFailed(false)
    prevCopyState.current = copyState
  }, [copyState])
  // Nothing this browser can play: an original it cannot decode and no copy to make (none lighter, or it failed).
  const noCopy = !!info && (info.auto == null || (copyState === 'error' && vq.target === info.auto) || copyRetries.current > 2)
  React.useEffect(() => {
    if (video && origBad && started && noCopy) onError?.()
  }, [video, origBad, started, noCopy, onError])
  const preparing = video && origBad && started && !onCopy && !noCopy

  // ---- position in this file (mediaMemory.ts): longer than 15 s, not a GIF-like clip
  const posKey = mediaPosKey(path, cur.ver)
  const remember = !gif && duration > 15
  const [resumeChip, setResumeChip] = React.useState<number | null>(null)
  const posChecked = React.useRef(false)
  const lastSave = React.useRef(0)
  const saveNow = React.useRef(() => {})
  saveNow.current = () => {
    if (remember && played.current && last.current.t > 0) setMediaPos(posKey, last.current.t)
  }
  React.useEffect(() => () => saveNow.current(), [])

  // ---- lost connection: reload the same source at the same time
  const [lost, setLost] = React.useState<null | 'retrying' | 'failed'>(null)
  const tries = React.useRef(0)
  const retryTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const playIntent = React.useRef(false) // playing when the connection was lost
  const reload = React.useCallback(() => {
    const m = media.current
    clearTimeout(retryTimer.current)
    if (!m) return
    resume.current = { t: last.current.t, play: playIntent.current }
    setLost((l) => (l ? 'retrying' : l))
    m.load()
  }, [])
  const connectionLost = React.useCallback(() => {
    if (tries.current >= RETRY_MS.length) return setLost('failed')
    setLost('retrying')
    retryTimer.current = setTimeout(reload, RETRY_MS[tries.current++])
  }, [reload])
  React.useEffect(() => {
    if (!lost) return
    const again = () => {
      if (document.visibilityState !== 'visible') return
      tries.current = 0
      reload()
    }
    document.addEventListener('visibilitychange', again)
    window.addEventListener('online', again)
    // after the 3 tries: ask the server every 5 s, quietly, and resume as soon as it answers
    const poll = lost === 'failed' ? setInterval(() => void reach(last.current.src).then((r) => r === 'ok' && again()), 5000) : undefined
    return () => {
      document.removeEventListener('visibilitychange', again)
      window.removeEventListener('online', again)
      clearInterval(poll)
    }
  }, [lost, reload])
  const back = () => {
    if (!lost) return
    tries.current = 0
    setLost(null)
  }

  // Controls fade out after 2.5 s without moving while a video plays.
  const poke = React.useCallback(() => {
    setIdle(false)
    clearTimeout(idleTimer.current)
    idleTimer.current = setTimeout(() => setIdle(true), 2500)
  }, [])
  React.useEffect(() => () => {
    clearTimeout(idleTimer.current)
    clearTimeout(volTimer.current)
    clearTimeout(waitTimer.current)
    clearTimeout(retryTimer.current)
    clearTimeout(seekTimer.current)
  }, [])
  // The original struggles while a lighter copy is possible: buffering > 1.5 s, or > 20 % frames dropped.
  const waitTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const watchRough = video && vq.choice === 'auto' && info?.auto != null && !rough && !onCopy
  React.useEffect(() => {
    if (!watchRough || !playing) return
    const v = media.current as HTMLVideoElement | null
    let prev = v?.getVideoPlaybackQuality?.()
    const id = setInterval(() => {
      const q = v?.getVideoPlaybackQuality?.()
      if (!q || !prev) return
      const total = q.totalVideoFrames - prev.totalVideoFrames
      if (total >= 20 && (q.droppedVideoFrames - prev.droppedVideoFrames) / total > 0.2) setRough(true)
      prev = q
    }, 2000)
    return () => clearInterval(id)
  }, [watchRough, playing])
  React.useEffect(() => {
    const onFs = () => setFullscreen(document.fullscreenElement === root.current)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  // ---- the element: rendered below, or (keepAlive audio) taken from sharedAudio
  const setMediaEl = React.useCallback((m: HTMLMediaElement | null) => {
    media.current = m
    setEl(m)
  }, [])
  React.useLayoutEffect(() => {
    if (!shared) return
    const a = takeAudio(path)
    if (a.getAttribute('src')) {
      // still playing (or paused) from an earlier mount: show where it is
      played.current = a.currentTime > 0 || !a.paused
      posChecked.current = true
      last.current = { t: a.currentTime, play: !a.paused, src: a.getAttribute('src')! }
      setCur((c) => ({ ...c, src: a.getAttribute('src')! }))
      setStarted(played.current)
      setPlaying(!a.paused)
      setTime(a.currentTime)
      setDuration(Number.isFinite(a.duration) ? a.duration : 0)
      setVolume(a.volume)
      setMuted(a.muted)
      setSpeed(a.playbackRate)
    }
    setMediaEl(a)
    return () => {
      setMediaEl(null)
      releaseAudio(path)
    }
  }, [shared, path, setMediaEl])
  React.useEffect(() => {
    if (shared && el && el.getAttribute('src') !== src && (el.paused || el.ended)) el.src = src
  }, [shared, el, src])
  // Saved volume, mute and speed on a new element (a GIF-like clip: muted, looped, normal speed).
  React.useEffect(() => {
    if (!el || (shared && played.current)) return
    if (gif) {
      el.muted = true
      el.loop = true
      el.defaultPlaybackRate = el.playbackRate = 1
      if (el.paused && !el.ended) void el.play().catch(() => {})
      return
    }
    el.loop = false
    if (canSetVolume()) el.volume = prefs.volume
    el.muted = prefs.muted
    el.defaultPlaybackRate = el.playbackRate = prefs.speed
  }, [el, gif, prefs, shared])

  const toggle = () => {
    const m = media.current
    if (!m) return
    if (m.paused || m.ended) {
      setStarted(true) // asked to play: the Auto copy may start (even when this browser cannot read the original)
      playIntent.current = true
      // where `volume` is read-only (iPhone): the saved level goes through the gain, set up now (a user gesture)
      if (!canSetVolume() && !gif && gainVol.current == null && prefs.volume < 1) setVol(prefs.volume)
      if (video && origBad && !onCopy) {
        last.current.play = true // the copy starts playing when ready
        return
      }
      void m.play().catch(() => {})
    } else {
      playIntent.current = false
      m.pause()
    }
  }
  const seek = (to: number) => {
    const m = media.current
    if (!m || !Number.isFinite(m.duration)) return
    m.currentTime = Math.max(0, Math.min(m.duration, to))
    setTime(m.currentTime)
  }
  const setVol = (v: number) => {
    const m = media.current
    if (!m) return
    v = Math.max(0, Math.min(1, v))
    if (!canSetVolume()) {
      const g = gainFor(m)
      if (g) {
        g.gain.value = v
        gainVol.current = v
        setVolume(v)
        if (!gif) savePrefs({ volume: v })
      }
      m.muted = v === 0
      return
    }
    m.volume = v
    m.muted = v === 0
  }
  const coarse = () => window.matchMedia('(pointer: coarse)').matches
  const keepVolOpen = () => {
    clearTimeout(volTimer.current)
    volTimer.current = setTimeout(() => setVolOpen(false), 3500)
  }
  const onVolButton = () => {
    const m = media.current
    if (!m) return
    if (coarse() && !volOpen) {
      setVolOpen(true)
      keepVolOpen()
      poke()
      return
    }
    m.muted = !m.muted
    if (volOpen) keepVolOpen()
  }
  const setRate = (r: number) => {
    const m = media.current
    if (m) m.defaultPlaybackRate = m.playbackRate = r
  }
  /** One step up / down the speed list (keys > and <). */
  const stepSpeed = (dir: 1 | -1) => {
    const m = media.current
    if (!m) return
    const next = dir > 0 ? SPEEDS.find((x) => x > m.playbackRate + 1e-3) : [...SPEEDS].reverse().find((x) => x < m.playbackRate - 1e-3)
    if (next) setRate(next)
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

  // ---- progress bar: the drag position shows at once, the media seeks at most every 150 ms (each seek of a video
  // not buffered there is a new Range request), and once more where the pointer is released
  const timeAt = (clientX: number) => {
    const r = bar.current?.getBoundingClientRect()
    if (!r || !duration) return 0
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration
  }
  const seekTimer = React.useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const lastSeek = React.useRef(0)
  const pendingSeek = React.useRef<number | null>(null)
  const flushSeek = () => {
    clearTimeout(seekTimer.current)
    seekTimer.current = undefined
    if (pendingSeek.current == null) return
    lastSeek.current = performance.now()
    seek(pendingSeek.current)
    pendingSeek.current = null
  }
  const dragTo = (to: number) => {
    setDragT(to)
    pendingSeek.current = to
    const wait = SEEK_EVERY_MS - (performance.now() - lastSeek.current)
    if (wait <= 0) flushSeek()
    else seekTimer.current ??= setTimeout(flushSeek, wait)
  }
  const onBarDown = (e: React.PointerEvent) => {
    e.preventDefault()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
    dragTo(timeAt(e.clientX))
  }
  const onBarMove = (e: React.PointerEvent) => {
    const r = bar.current?.getBoundingClientRect()
    if (r) setHover({ x: Math.max(0, Math.min(r.width, e.clientX - r.left)), t: timeAt(e.clientX) })
    if (dragT != null) dragTo(timeAt(e.clientX))
  }
  const onBarUp = (e: React.PointerEvent) => {
    if (dragT == null) return
    pendingSeek.current = e.type === 'pointercancel' ? dragT : timeAt(e.clientX)
    flushSeek()
    setDragT(null)
  }

  const onKey = (e: React.KeyboardEvent) => {
    if (e.altKey || e.ctrlKey || e.metaKey) return
    const target = e.target as HTMLElement
    if (target.tagName === 'SELECT') return // the speed / quality picker has its own keys
    // the volume slider: its arrows (and Home / End / Page keys) move the volume, not the time
    if (target instanceof HTMLInputElement && target.type === 'range' && /^(Arrow|Home|End|Page)/.test(e.key)) {
      e.stopPropagation()
      return
    }
    const k = e.key.toLowerCase()
    const m = media.current
    if (!m) return
    let handled = true
    if (e.key === '>') stepSpeed(1)
    else if (e.key === '<') stepSpeed(-1)
    else if (k === ' ' || k === 'k') toggle()
    else if (k === 'arrowleft') seek(m.currentTime - 5)
    else if (k === 'arrowright') seek(m.currentTime + 5)
    else if (k === 'j') seek(m.currentTime - 10)
    else if (k === 'l') seek(m.currentTime + 10)
    else if (k === 'arrowup') setVol((m.muted ? 0 : volume) + 0.1)
    else if (k === 'arrowdown') setVol((m.muted ? 0 : volume) - 0.1)
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

  const shownT = dragT ?? time
  const pct = duration ? (shownT / duration) * 100 : 0
  const showControls = !video || !playing || !idle || dragT != null || volOpen
  const VolIcon = muted || volume === 0 ? VolumeX : volume < 0.5 ? Volume1 : Volume2
  const touchVolHidden = !volOpen && typeof window !== 'undefined' && window.matchMedia?.('(pointer: coarse)').matches

  const controls = (
    // video: the shaded band lets taps through to the picture (only the bar and the buttons take them)
    <div className={cn('flex flex-col gap-1.5', video ? 'pointer-events-none px-3 pt-8 pb-2.5 text-white [background:linear-gradient(to_top,rgb(0_0_0/0.72),transparent)]' : 'text-foreground', video && showControls && '[&>*]:pointer-events-auto')}>
      {/* progress */}
      <div
        ref={bar}
        role="slider"
        tabIndex={-1}
        aria-label={t('media.seek')}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(shownT)}
        aria-valuetext={`${fmt(shownT)} / ${fmt(duration)}`}
        onPointerDown={onBarDown}
        onPointerMove={onBarMove}
        onPointerUp={onBarUp}
        onPointerCancel={onBarUp}
        onPointerLeave={() => setHover(null)}
        data-testid="media-bar"
        className="group/bar relative flex h-4 cursor-pointer max-md:h-10 pointer-coarse:h-10 touch-none items-center"
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
          <CtrlButton label={muted ? t('media.unmute') : t('media.mute')} onClick={onVolButton} video={video}>
            <VolIcon className="size-[18px]" />
          </CtrlButton>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            tabIndex={touchVolHidden ? -1 : undefined}
            onChange={(e) => {
              setVol(Number(e.target.value))
              if (volOpen) keepVolOpen()
              poke()
            }}
            aria-label={t('media.volume')}
            data-testid="media-volume"
            className={cn(
              'h-1 w-0 cursor-pointer accent-[var(--primary)] opacity-0 transition-all pointer-coarse:h-10',
              volOpen ? 'ml-1 w-24 opacity-100' : 'group-focus-within/vol:w-20 group-focus-within/vol:opacity-100 group-hover/vol:w-20 group-hover/vol:opacity-100 pointer-coarse:hidden',
            )}
          />
        </div>
        <span className={cn('ml-1 text-xs whitespace-nowrap tabular-nums', video ? 'text-white/90' : 'text-muted-foreground', volOpen && 'max-sm:hidden')}>
          {fmt(shownT)} <span className="opacity-60">/ {fmt(duration)}</span>
        </span>
        <span className="flex-1" />
        {video && !!vq.info?.qualities.length && (
          <PickButton
            label={t('media.quality')}
            testid="quality"
            value={String(vq.choice)}
            options={qualityOptions(vq.info, t)}
            onPick={(v) => {
              picked.current = true
              vq.setChoice(v === 'auto' || v === 'original' ? v : Number(v))
              setCopyFailed(false)
            }}
            video={video}
          >
            <span className="relative text-xs font-semibold tabular-nums">
              {onCopy ? `${vq.playing}p` : vq.choice === 'auto' ? 'Auto' : `${vq.info.height}p`}
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
          <CtrlButton label={t('media.pip')} onClick={pip} video={video} className="max-[399px]:hidden">
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

  const [natural, setNatural] = React.useState<{ w: number; h: number } | null>(null)
  useMediaEvents(el, {
    play: () => {
      last.current.play = true
      playIntent.current = true
      played.current = true
      setPlaying(true)
      setStarted(true)
      setEnded(false)
      setResumeChip(null)
      if (!gif) poke()
    },
    pause: (m) => {
      // A source switch (or a reload after a lost connection) pauses on its own: that pause must not stop the
      // playback that resumes after it.
      if (!m.ended && m.currentTime === 0 && resume.current) return
      if (m.error || lost) return
      last.current.play = false
      setPlaying(false)
      saveNow.current()
    },
    ended: () => {
      setPlaying(false)
      setEnded(true)
      playIntent.current = false
      clearMediaPos(posKey)
    },
    waiting: () => {
      setWaiting(true)
      clearTimeout(waitTimer.current)
      // the original struggles: > 1.5 s of buffering; nothing comes for 15 s: the connection may be gone
      waitTimer.current = setTimeout(
        () => {
          if (watchRough && played.current) setRough(true)
          else if (src) void reach(src).then((r) => r === 'down' && connectionLost())
        },
        watchRough && played.current ? 1500 : 15000,
      )
    },
    playing: () => {
      played.current = true
      setWaiting(false)
      clearTimeout(waitTimer.current)
      back()
    },
    canplay: () => {
      setWaiting(false)
      clearTimeout(waitTimer.current)
      back()
    },
    timeupdate: (m) => {
      if (resume.current) return // a reload or a source switch on its way: the time to resume is kept
      last.current.t = m.currentTime
      if (dragT == null) setTime(m.currentTime)
      if (Date.now() - lastSave.current > 2000) {
        lastSave.current = Date.now()
        saveNow.current()
      }
    },
    loadedmetadata: (m) => {
      setDuration(m.duration)
      const v = m as HTMLVideoElement
      if (video && v.videoWidth && v.videoHeight) setNatural({ w: v.videoWidth, h: v.videoHeight })
      // where `volume` is read-only, the gain stays on the element: set its level again after a source change
      if (gainVol.current != null) {
        const g = gainFor(m)
        if (g) g.gain.value = gainVol.current
      }
      const r = resume.current
      resume.current = null
      // opened again: back where it was left (not for a short or GIF-like clip)
      const at = !posChecked.current && !gif && m.duration > 15 ? resumePos(posKey, m.duration) : null
      posChecked.current = true
      if (r && r.t > 0) m.currentTime = Math.min(r.t, m.duration || r.t)
      else if (at != null && m.currentTime < 1) {
        m.currentTime = at
        last.current.t = at
        setTime(at)
        if (!r?.play) setResumeChip(at)
      }
      if (r) {
        m.playbackRate = speed
        if (r.play) void m.play().catch(() => {})
      }
    },
    durationchange: (m) => setDuration(m.duration),
    progress: (m) => {
      const b = m.buffered
      const now = m.currentTime
      for (let i = 0; i < b.length; i++) if (b.start(i) <= now + 0.5) setBuffered(b.end(i))
    },
    volumechange: (m) => {
      const v = gainVol.current ?? m.volume // the gain's level where `volume` is read-only
      setVolume(v)
      setMuted(m.muted)
      if (!gif) savePrefs(canSetVolume() ? { volume: v, muted: m.muted } : { muted: m.muted })
    },
    ratechange: (m) => {
      setSpeed(m.playbackRate)
      if (!gif) savePrefs({ speed: m.playbackRate })
    },
    error: (m) => {
      const err = m.error
      if (!err || err.code === 1) return // MEDIA_ERR_ABORTED: a new source replaced this one
      const at = m.currentTime || last.current.t
      if (at > 0) last.current.t = at
      // A network error, or a decode / format error - which is also what the browser says when the server did not
      // answer at all (restarting): ask the server what it serves for this URL now.
      const failed = src
      void reach(failed).then((r) => {
        if (media.current !== m || last.current.src !== failed) return
        if (r === 'down' || (r === 'ok' && err.code === 2)) return connectionLost() // 2: MEDIA_ERR_NETWORK
        if (onCopy) {
          // the copy is gone (cache) or broken: the original meanwhile, the copy made again
          copyRetries.current++
          setCopyFailed(true)
          if (vq.target != null) vq.retry(vq.target)
          return
        }
        if (video && r === 'ok') {
          // an original this browser cannot read (HEVC, ProRes): the Auto copy is the way to play it - made once
          // Play is pressed (an error while only opening it starts no encoding)
          setOrigFailed(true)
          last.current.play = last.current.play || playIntent.current
          return
        }
        onError?.()
      })
    },
    webkitbeginfullscreen: () => setFullscreen(true), // iPhone: the video alone in the system player
    webkitendfullscreen: () => setFullscreen(false),
  })

  const chips = (
    <>
      {lost && (
        <span className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white shadow-pop" role="status" data-testid="media-lost">
          {lost === 'retrying' ? (
            <>
              <Spinner className="size-3.5" />
              {t('media.lost')}
            </>
          ) : (
            <>
              {t('media.lostFailed')}
              <span className="opacity-60">·</span>
              <button type="button" className="font-medium underline-offset-2 hover:underline" onClick={() => ((tries.current = 0), reload())}>
                {t('common.retry')}
              </button>
            </>
          )}
        </span>
      )}
      {changed && !lost && (
        <span className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white shadow-pop" data-testid="media-changed">
          {t('media.changed')}
          <span className="opacity-60">·</span>
          <button type="button" className="font-medium underline-offset-2 hover:underline" onClick={reloadChanged}>
            {t('media.reload')}
          </button>
        </span>
      )}
      {resumeChip != null && !playing && !lost && (
        <span className="pointer-events-auto inline-flex items-center gap-1.5 rounded-full bg-black/70 px-2.5 py-1 text-xs text-white shadow-pop" data-testid="media-resume">
          {t('media.resumeAt', { time: fmt(resumeChip) })}
          <span className="opacity-60">·</span>
          <button
            type="button"
            className="font-medium underline-offset-2 hover:underline"
            onClick={() => {
              seek(0)
              last.current.t = 0
              clearMediaPos(posKey)
              setResumeChip(null)
            }}
          >
            {t('media.fromStart')}
          </button>
        </span>
      )}
    </>
  )

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
            {(waiting && playing) || lost === 'retrying' ? <Spinner className="size-5" /> : playing ? <Pause className="size-5 fill-current" /> : <Play className="ml-0.5 size-5 fill-current" />}
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
        {(lost || changed || resumeChip != null) && <div className="flex flex-wrap gap-1.5">{chips}</div>}
        {controls}
        {!shared && <audio ref={setMediaEl} key={path} src={src} preload="metadata" className="hidden" />}
      </div>
    )

  // The box has the video's shape before anything loads: its size from the server, then from the file itself.
  // It fits the space around it (a container: MediaView) like the picture would - no 300x150 frame, no jump.
  const dims = natural ?? (info ? shownSize(info) : null)
  const ratio = dims && dims.w > 0 && dims.h > 0 ? `${dims.w} / ${dims.h}` : '16 / 9'
  const boxW = dims && dims.w > 0 && dims.h > 0 ? `min(${dims.w}px, 100cqw, calc(100cqh * ${dims.w} / ${dims.h}))` : 'min(48rem, 100cqw, calc(100cqh * 16 / 9))'
  return (
    <div
      ref={root}
      tabIndex={0}
      onKeyDown={onKey}
      data-media-player
      data-gif={gif || undefined}
      onPointerMove={poke}
      onPointerLeave={() => gif && playing && setIdle(true)}
      style={{ width: boxW, aspectRatio: ratio }}
      className={cn(
        'group/player relative flex max-w-full overflow-hidden rounded-xl bg-black shadow-pop outline-none focus-visible:ring-2 focus-visible:ring-ring',
        fullscreen && 'rounded-none',
        playing && idle && 'cursor-none',
        className,
      )}
    >
      <video
        ref={setMediaEl as React.Ref<HTMLVideoElement>}
        key={path}
        src={src}
        poster={poster}
        preload={gif ? 'auto' : 'metadata'}
        playsInline
        onPointerDown={(e) => (controlsAtDown.current = { shown: showControls, touch: e.pointerType !== 'mouse' })}
        onClick={() => {
          // touch: a first tap shows the controls, a tap while they show plays / pauses
          if (controlsAtDown.current.touch && !controlsAtDown.current.shown) return poke()
          toggle()
          if (gif) poke()
        }}
        onDoubleClick={toggleFullscreen}
        className="size-full object-contain"
      />
      {/* centre: big play / spinner / a copy being made */}
      {preparing ? (
        <div className="absolute inset-0 m-auto flex h-fit w-fit max-w-[80%] items-center gap-2 rounded-full bg-black/70 px-3 py-2 text-sm text-white" role="status" data-testid="media-preparing">
          <Spinner className="size-4" />
          {t('media.preparing', { pct: vq.targetState?.state === 'running' ? `${Math.round(vq.targetState.progress * 100)} %` : '' })}
        </div>
      ) : (
        (!playing || (waiting && started)) && (
          <button
            type="button"
            onClick={toggle}
            aria-label={ended ? t('media.replay') : t('media.play')}
            className="absolute inset-0 z-10 m-auto flex size-16 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-pop transition-transform hover:scale-105 focus-visible:ring-2 focus-visible:ring-white focus-visible:outline-none"
          >
            {(waiting && started) || lost === 'retrying' ? <Spinner className="size-7" /> : ended ? <RotateCcw className="size-7" /> : <Play className="ml-1 size-7 fill-current" />}
          </button>
        )
      )}
      <div className="pointer-events-none absolute top-2.5 left-2.5 flex flex-col items-start gap-1.5">{chips}</div>
      <div className={cn('pointer-events-none absolute inset-x-0 bottom-0 transition-opacity duration-300', showControls ? 'opacity-100' : 'opacity-0')}>{controls}</div>
    </div>
  )
}

function CtrlButton({ label, onClick, video, className, children }: { label: string; onClick: () => void; video: boolean; className?: string; children: React.ReactNode }) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        className={cn(
          'flex size-8 shrink-0 items-center justify-center rounded-md transition-colors max-md:size-10 pointer-coarse:size-10 focus-visible:ring-2 focus-visible:outline-none',
          video ? 'text-white/90 hover:bg-white/15 hover:text-white focus-visible:ring-white/70' : 'text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:ring-ring',
          className,
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
          'relative flex h-8 min-w-8 shrink-0 items-center max-md:h-10 max-md:min-w-10 pointer-coarse:h-10 pointer-coarse:min-w-10 justify-center rounded-md px-1 transition-colors has-[select:focus-visible]:ring-2',
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
