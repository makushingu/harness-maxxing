// sRGB values of the accent colors (globals.css defines them in oklch). Used where CSS variables cannot reach:
// the favicon (an image) and the splash painted before the stylesheet. index.html keeps a copy - change both.
import type { Accent } from '@/stores/ui'

export const ACCENT_HEX: Record<'light' | 'dark', Record<Accent, string>> = {
  light: { blue: '#0076ed', clay: '#ea7e00', violet: '#a126d7', green: '#25931c', amber: '#e0bb00', rose: '#e62e1e' },
  dark: { blue: '#3c91fd', clay: '#f8962d', violet: '#c25af3', green: '#55cc4b', amber: '#f1d025', rose: '#fc523a' },
}

/** The product logo in the accent color, vector (public/icons/logo-<accent>.svg - sharp at any size; made by
 *  web/scripts/gen-icons.py with the PNG versions). */
export const logoSrc = (accent: Accent) => `/icons/logo-${ACCENT_HEX.dark[accent] ? accent : 'blue'}.svg`

const known = (accent: Accent) => (ACCENT_HEX.dark[accent] ? accent : 'blue')

/** App icon in the accent color (installed app, notifications): public/icons/icon-<accent>-192.png. */
export const appIconSrc = (accent: Accent) => `/icons/icon-${known(accent)}-192.png`

function setLink(rel: string, href: string, type?: string) {
  let link = document.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`)
  if (!link) {
    link = document.createElement('link')
    link.rel = rel
    document.head.appendChild(link)
  }
  if (link.getAttribute('href') !== href) {
    if (type) link.type = type
    link.href = href
  }
}

/** Every icon follows the accent: browser tab, installed app (manifest icons and launch screen), iOS home screen.
 *  index.html does the same before the first paint - change both. */
export function applyFavicon(accent: Accent) {
  setLink('icon', logoSrc(accent), 'image/svg+xml')
  setLink('manifest', `/manifest-${known(accent)}.webmanifest`)
  setLink('apple-touch-icon', `/icons/apple-touch-icon-${known(accent)}.png`)
}
