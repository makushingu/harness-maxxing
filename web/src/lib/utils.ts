import type * as React from 'react'
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

/** Merge class names, resolving Tailwind conflicts (last one wins). */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Label → API slug: `^[a-z0-9][a-z0-9-]{0,47}$` (see API.md Workspace). */
export function slugify(label: string): string {
  return label
    .normalize('NFKD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 48)
    .replace(/-+$/g, '')
}

export const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,47}$/

export function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms))
}

/** The window the user is typing in: the HUD (Document Picture-in-Picture) when it has the focus - the
 * clipboard of an unfocused document refuses to write. */
function focusedWindow(): Window {
  const pip = (window as unknown as { documentPictureInPicture?: { window: Window | null } }).documentPictureInPicture?.window
  return pip && pip.document.hasFocus() ? pip : window
}

export async function copyText(text: string): Promise<boolean> {
  const w = focusedWindow()
  try {
    await w.navigator.clipboard.writeText(text)
    return true
  } catch {
    // Fallback for non-secure contexts (plain http on a LAN/Tailscale IP).
    try {
      const doc = w.document
      const ta = doc.createElement('textarea')
      ta.value = text
      ta.setAttribute('readonly', '')
      ta.style.position = 'fixed'
      ta.style.opacity = '0'
      doc.body.appendChild(ta)
      ta.select()
      const ok = doc.execCommand('copy')
      ta.remove()
      return ok
    } catch {
      return false
    }
  }
}

export const isMac = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform)

/** Merge refs (callback or object) into one callback ref (memoize it: a new ref re-attaches on every render). */
export function mergeRefs<T>(...refs: (React.Ref<T> | undefined)[]): React.RefCallback<T> {
  return (node) => {
    const cleanups = refs.map((r) => {
      if (typeof r === 'function') {
        const c = r(node)
        return typeof c === 'function' ? c : () => r(null)
      }
      if (r) (r as React.RefObject<T | null>).current = node
      return () => {
        if (r) (r as React.RefObject<T | null>).current = null
      }
    })
    return () => cleanups.forEach((c) => c())
  }
}

/** localStorage that never throws: a browser blocking storage (every cookie refused) or a full quota just
 *  forgets instead of breaking the page. */
export const store = {
  get(k: string): string | null {
    try {
      return localStorage.getItem(k)
    } catch {
      return null
    }
  },
  set(k: string, v: string): void {
    try {
      localStorage.setItem(k, v)
    } catch {
      /* blocked / quota */
    }
  },
  remove(k: string): void {
    try {
      localStorage.removeItem(k)
    } catch {
      /* blocked */
    }
  },
}
