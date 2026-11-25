/** The secret of one mounted HTML widget, given to its frame in the URL fragment (see HtmlWidget). */
export function frameKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Whether the document now in the frame is the widget: every document loaded there (`loads`) greeted the host with
 * the key (`hellos`). A page a link loaded into the frame does not know the key: it gets no data nor theme. The two
 * counts may arrive in either order, so a greeting ahead of its load counts too. */
export function ours(seen: { loads: number; hellos: number }): boolean {
  return seen.hellos >= seen.loads
}
