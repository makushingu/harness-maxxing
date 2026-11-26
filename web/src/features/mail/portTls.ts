/** The security that follows the port typed in the account dialog (AccountDialog). A well-known port (993, 465, 587…)
 * sets its own; the security it replaced is kept with that port and given back only while the user types through it
 * ("25" on the way to "2525"). A known port the user stopped on, then corrected (587 -> 58 -> 588), keeps its security. */
export type KeptTls<T extends string> = { tls: T; port: string }

export function portTls<T extends string>(
  v: string,
  tls: T,
  kept: KeptTls<T> | undefined,
  known: Record<string, T>,
): { tls: T; kept: KeptTls<T> | undefined } {
  const port = v.trim()
  const k = Object.prototype.hasOwnProperty.call(known, port) ? known[port] : undefined
  if (k) return { tls: k, kept: kept && port.startsWith(kept.port) ? kept : { tls: kept?.tls ?? tls, port } }
  if (kept && port.length > kept.port.length && port.startsWith(kept.port)) return { tls: kept.tls, kept: undefined }
  return { tls, kept: undefined }
}
