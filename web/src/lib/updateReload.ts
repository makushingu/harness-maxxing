// The server was updated while this page stayed open (a PWA resumed from the background, a tab left open over
// `maxxing update`): the parts of the previous build are gone. Not an error for the user - reload, quietly.

/** A chunk of a previous build is gone from the server: a reload fixes it. */
export const isChunkError = (e: unknown) =>
  e instanceof Error && /dynamically imported module|Importing a module script failed|Failed to fetch dynamically|Unable to preload/i.test(e.message)

const KEY = 'mx-chunk-reload'

/** Reload to get the new build, once a minute at most (no loop when the server is really broken).
 *  false = not reloading (just tried, or no storage to tell a loop apart): show the calm "Reload" screen. */
export function reloadForUpdate(): boolean {
  try {
    if (Date.now() - Number(sessionStorage.getItem(KEY) || 0) < 60_000) return false
    sessionStorage.setItem(KEY, String(Date.now()))
  } catch {
    return false
  }
  window.location.reload()
  return true
}
