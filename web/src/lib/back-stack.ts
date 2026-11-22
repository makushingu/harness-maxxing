// Phone Back (Android button or gesture, browser Back) closes the drawer or dialog on top instead of leaving the page.
// Each open overlay pushes one history entry with the same URL, marked `mxBack`; Back pops it and closes that overlay.
// Pure (no runtime import) so the tests run it on a fake window.

type Win = { history: History; addEventListener: (type: 'popstate', fn: () => void) => void }
type Entry = { id: number; close: () => void }

export function createBackStack(win: Win) {
  const open: Entry[] = []
  let seq = Date.now() // ids grow across reloads too, like the history entries they mark
  let ignore = 0
  const here = (): number | undefined => (win.history.state as { mxBack?: number } | null)?.mxBack
  win.addEventListener('popstate', () => {
    if (ignore) return void ignore--
    const at = here()
    // Back left the entries of these overlays: close them, top first.
    while (open.length && open[open.length - 1].id > (at ?? 0)) open.pop()!.close()
    // An entry left behind by an overlay closed while the page changed: step over it.
    if (at !== undefined && !open.some((e) => e.id === at)) win.history.back()
  })
  return {
    /** Call when an overlay opens; call the result when it closes (`busy`: a navigation is still in flight). */
    push(close: () => void) {
      const e = { id: ++seq, close }
      win.history.pushState({ ...(win.history.state as object | null), mxBack: e.id }, '')
      open.push(e)
      return (busy = false) => {
        const i = open.indexOf(e)
        if (i < 0) return
        open.splice(i, 1)
        // Closed from the page (X, swipe, a choice): drop its entry, unless a navigation started from it
        // (going back now would cancel that navigation; the entry is stepped over later instead).
        if (here() === e.id && !busy) {
          ignore++
          win.history.back()
        }
      }
    },
  }
}
