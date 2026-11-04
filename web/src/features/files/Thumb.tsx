// A file's thumbnail that follows the file: its URL carries the file's current mtime (useFileStamp), so an image
// or a video rewritten under the same name shows its new version - and an unchanged one stays in the browser cache.
// Give it a box of fixed size (className): the placeholder and the image fill it, nothing changes width when the
// image arrives. `anim`: a GIF moves (the original when it is at most 8 MB, else a still).
// A file that does not exist yet keeps the placeholder until its stamp shows it (asked again by useFileStamp); a
// thumbnail that fails (a video still being written, a busy server) is asked again a few times, never left broken.
import * as React from 'react'
import { fileThumbUrl, useFileStamp } from '@/lib/queries/files'
import { cn } from '@/lib/utils'

type Props = { path: string; w: number; anim?: boolean } & Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'>

const RETRY_MS = [1000, 2000, 4000, 8000, 15_000, 30_000, 30_000, 30_000]

export function Thumb({ path, w, anim, alt = '', onError, ...img }: Props) {
  const { ready, version, recheck } = useFileStamp(path)
  const key = `${path}|${version}`
  // failures of this version of the file (a new version starts over)
  const [fail, setFail] = React.useState({ key: '', n: 0, waiting: false })
  const n = fail.key === key ? fail.n : 0
  const waiting = fail.key === key && fail.waiting
  React.useEffect(() => {
    if (!waiting) return
    const t = window.setTimeout(() => {
      // the file may have changed meanwhile (new stamp = new URL); else the same URL is asked again
      void recheck().finally(() => setFail((f) => (f.key === key ? { ...f, waiting: false } : f)))
    }, RETRY_MS[n - 1])
    return () => window.clearTimeout(t)
  }, [waiting, key, n, recheck])
  // One batched round trip before the first paint: never an unversioned load followed by a second one.
  if (!ready || version === null || waiting || n > RETRY_MS.length) return <span aria-hidden className={cn('inline-block min-w-16 bg-muted', img.className)} />
  return (
    <img
      src={fileThumbUrl(path, w, version, anim && /\.gif$/i.test(path), n)}
      alt={alt}
      onError={(e) => {
        setFail({ key, n: n + 1, waiting: n < RETRY_MS.length })
        onError?.(e)
      }}
      {...img}
    />
  )
}
