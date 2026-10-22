// Download a file. Images and PDFs the page has usually just shown (viewer, preview, chat thumbnail opened) are
// read back from the browser cache - the same URL as the one displayed, so at most a 304 - and saved at once:
// the `?download=1` URL is another cache entry and made the browser fetch the whole file again. Other files
// (videos, archives...) keep the browser's own download, which streams to disk and shows its progress.
import type * as React from 'react'
import { fileRawUrl } from '@/lib/queries/files'
import { basename, kindOf } from './kinds'

const FROM_CACHE = new Set(['image', 'pdf'])

function save(href: string, name: string) {
  const a = document.createElement('a')
  a.href = href
  a.download = name
  a.rel = 'noopener'
  document.body.appendChild(a)
  a.click()
  a.remove()
}

export async function downloadFile(path: string, version?: number | null): Promise<void> {
  const name = basename(path)
  if (FROM_CACHE.has(kindOf(name))) {
    try {
      const res = await fetch(fileRawUrl(path, false, version), { credentials: 'same-origin' })
      if (res.ok) {
        const url = URL.createObjectURL(await res.blob())
        save(url, name)
        setTimeout(() => URL.revokeObjectURL(url), 60_000)
        return
      }
    } catch {
      /* the browser's own download below */
    }
  }
  save(fileRawUrl(path, true, version), name)
}

/** Props of a download `<a>`: a real link (middle click, "save link as"), the fast path on a plain click. */
export function downloadProps(path: string, version?: number | null) {
  return {
    href: fileRawUrl(path, true, version),
    download: basename(path),
    onClick: (e: React.MouseEvent) => {
      if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
      e.preventDefault()
      void downloadFile(path, version)
    },
  }
}
