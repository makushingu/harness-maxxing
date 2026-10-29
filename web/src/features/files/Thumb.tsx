// A file's thumbnail that follows the file: its URL carries the file's current mtime (useFileStamp), so an image
// or a video rewritten under the same name shows its new version - and an unchanged one stays in the browser cache.
// Give it a box of fixed size (className): the placeholder and the image fill it, nothing changes width when the
// image arrives. `anim`: a GIF moves (the original when it is at most 8 MB, else a still).
import * as React from 'react'
import { fileThumbUrl, useFileStamp } from '@/lib/queries/files'
import { cn } from '@/lib/utils'

type Props = { path: string; w: number; anim?: boolean } & Omit<React.ImgHTMLAttributes<HTMLImageElement>, 'src'>

export function Thumb({ path, w, anim, alt = '', ...img }: Props) {
  const { ready, version } = useFileStamp(path)
  // One batched round trip before the first paint: never an unversioned load followed by a second one.
  if (!ready) return <span aria-hidden className={cn('inline-block min-w-16 bg-muted', img.className)} />
  return <img src={fileThumbUrl(path, w, version, anim && /\.gif$/i.test(path))} alt={alt} {...img} />
}
