/** Work a page reload would lose (a message being sent, a file being uploaded): the automatic switch to a new
 *  build after an update waits for it to end. */
let n = 0
const EVENT = 'mx-busy'
export function busyStart() {
  n++
}
export function busyEnd() {
  if (n > 0 && --n === 0) window.dispatchEvent(new Event(EVENT))
}
export const isBusy = () => n > 0
/** Called once nothing is in progress any more. */
export function onIdle(fn: () => void): () => void {
  window.addEventListener(EVENT, fn)
  return () => window.removeEventListener(EVENT, fn)
}
