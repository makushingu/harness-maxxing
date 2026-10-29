// Audio players shown inline in a conversation keep playing when their message leaves the screen (the thread only
// renders what is near the view, a column switch unmounts it): their <audio> element is not in React's tree but
// owned here, one per file, outside the DOM (an Audio element plays without being attached). A player mounted
// again for that file takes the same element back and shows where it is. An element no player shows any more is
// dropped as soon as it is paused or ends.

type Entry = { el: HTMLAudioElement; users: number }
const live = new Map<string, Entry>()

function drop(key: string, e: Entry) {
  if (live.get(key) !== e) return
  live.delete(key)
  e.el.removeAttribute('src')
  e.el.load() // frees the connection and the decoded data
}

/** The element of `key` (a file path), created on first use. Give it back with releaseAudio. */
export function takeAudio(key: string): HTMLAudioElement {
  let e = live.get(key)
  if (!e) {
    const el = new Audio()
    el.preload = 'metadata'
    const entry: Entry = { el, users: 0 }
    const idle = () => {
      if (entry.users <= 0) drop(key, entry)
    }
    el.addEventListener('pause', idle)
    el.addEventListener('ended', idle)
    live.set(key, entry)
    e = entry
  }
  e.users++
  return e.el
}

export function releaseAudio(key: string) {
  const e = live.get(key)
  if (!e) return
  e.users--
  if (e.users <= 0 && (e.el.paused || e.el.ended)) drop(key, e)
}
