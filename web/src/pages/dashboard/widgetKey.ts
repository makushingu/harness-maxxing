/** The secret of one mounted HTML widget, given to its frame in the URL fragment (see HtmlWidget). */
export function frameKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Which document is in the frame. `gen` counts the documents loaded there; `okGen` is the one that greeted the host
 * with the key (-1: none). A page a link loaded into the frame does not know the key: it gets no data, theme nor
 * answer. The host pings the frame at each load, the widget greets back, and says goodbye when it leaves (pagehide). */
export type FrameState = { gen: number; okGen: number }

export const newFrame = (): FrameState => ({ gen: 0, okGen: -1 })

/** A document finished loading in the frame: unknown until it greets (the ping asks it to). */
export function frameLoaded(s: FrameState): void {
  s.gen++
}

/** A message with the key: the document in the frame now is the widget (even ahead of its own load event). */
export function frameHello(s: FrameState): void {
  s.okGen = s.gen
}

/** The widget's document is leaving (a link, Back): nothing more goes to the frame until a widget greets again. */
export function frameBye(s: FrameState): void {
  s.okGen = -1
}

export function ours(s: FrameState): boolean {
  return s.okGen === s.gen
}

/** Whether the answer to a request received at generation `asked` may go to the frame now: the widget is there and
 * it is the document that asked (`gen - 1`: asked before its own load event). */
export function mayReply(s: FrameState, asked: number): boolean {
  return ours(s) && asked >= s.gen - 1
}
