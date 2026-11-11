/** Passkeys (WebAuthn) in the browser: the server sends the options as JSON (binary fields in base64url), the
 *  browser wants ArrayBuffers, and the answer goes back as JSON. Written by hand rather than with
 *  PublicKeyCredential.parseCreationOptionsFromJSON / toJSON: password managers (Bitwarden, 1Password...) replace
 *  navigator.credentials with their own objects, which do not always have those. */

export const passkeysSupported = () => typeof window !== 'undefined' && !!window.PublicKeyCredential && !!navigator.credentials && window.isSecureContext

function fromB64url(s: string): ArrayBuffer {
  const b64 = s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4)
  const bin = atob(b64)
  const out = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i)
  return out.buffer
}

function toB64url(buf: ArrayBuffer | ArrayBufferView | null | undefined): string | null {
  if (!buf) return null
  const bytes = buf instanceof ArrayBuffer ? new Uint8Array(buf) : new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength)
  let bin = ''
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i])
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

type Descriptor = { id: string; type: 'public-key'; transports?: AuthenticatorTransport[] }

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Json = Record<string, any>

const descriptors = (list?: Descriptor[]) => list?.map((d) => ({ ...d, id: fromB64url(d.id) }))

/** navigator.credentials.create() with the server's options -> the JSON the server verifies. */
export async function createPasskey(o: Json): Promise<Json> {
  const publicKey: PublicKeyCredentialCreationOptions = {
    ...o,
    challenge: fromB64url(o.challenge),
    user: { ...o.user, id: fromB64url(o.user.id) },
    excludeCredentials: descriptors(o.excludeCredentials),
  } as PublicKeyCredentialCreationOptions
  const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null
  if (!cred) throw new DOMException('No passkey', 'NotAllowedError')
  const r = cred.response as AuthenticatorAttestationResponse
  return {
    id: cred.id,
    rawId: toB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64url(r.clientDataJSON),
      attestationObject: toB64url(r.attestationObject),
      transports: typeof r.getTransports === 'function' ? r.getTransports() : [],
    },
    clientExtensionResults: typeof cred.getClientExtensionResults === 'function' ? cred.getClientExtensionResults() : {},
    authenticatorAttachment: cred.authenticatorAttachment ?? null,
  }
}

/** Can the browser offer passkeys in the autofill of a field (conditional mediation)? */
export async function autofillSupported(): Promise<boolean> {
  try {
    return passkeysSupported() && typeof PublicKeyCredential.isConditionalMediationAvailable === 'function' && (await PublicKeyCredential.isConditionalMediationAvailable())
  } catch {
    return false
  }
}

/** navigator.credentials.get() with the server's options -> the JSON the server verifies. `conditional`: offered in
 *  the autofill of a field marked `autocomplete="... webauthn"` instead of a window. */
export async function getPasskey(o: Json, how: { conditional?: boolean; signal?: AbortSignal } = {}): Promise<Json> {
  const publicKey: PublicKeyCredentialRequestOptions = {
    ...o,
    challenge: fromB64url(o.challenge),
    allowCredentials: descriptors(o.allowCredentials),
  } as PublicKeyCredentialRequestOptions
  const cred = (await navigator.credentials.get({ publicKey, signal: how.signal, ...(how.conditional ? { mediation: 'conditional' as CredentialMediationRequirement } : {}) })) as PublicKeyCredential | null
  if (!cred) throw new DOMException('No passkey', 'NotAllowedError')
  const r = cred.response as AuthenticatorAssertionResponse
  return {
    id: cred.id,
    rawId: toB64url(cred.rawId),
    type: cred.type,
    response: {
      clientDataJSON: toB64url(r.clientDataJSON),
      authenticatorData: toB64url(r.authenticatorData),
      signature: toB64url(r.signature),
      userHandle: toB64url(r.userHandle),
    },
    clientExtensionResults: typeof cred.getClientExtensionResults === 'function' ? cred.getClientExtensionResults() : {},
    authenticatorAttachment: cred.authenticatorAttachment ?? null,
  }
}

// ---- Signal API: keep the password manager in step with the server (Chrome 132+, others ignore it) ----
type Signals = {
  signalUnknownCredential?: (o: { rpId: string; credentialId: string }) => Promise<void>
  signalAllAcceptedCredentials?: (o: { rpId: string; userId: string; allAcceptedCredentialIds: string[] }) => Promise<void>
}
const signals = () => (typeof window !== 'undefined' && window.PublicKeyCredential ? (window.PublicKeyCredential as unknown as Signals) : {})

/** Can this browser tell the password manager that a passkey is gone? (Chrome / Edge 132+, recent Safari) */
export const signalSupported = () => typeof signals().signalUnknownCredential === 'function'

/** A passkey the server does not know any more (removed in Settings): the password manager hides or deletes it. */
export function signalUnknown(rpId: string, credentialId: string) {
  signals().signalUnknownCredential?.({ rpId, credentialId }).catch(() => undefined)
}

/** The passkeys this server accepts for this host: the password manager drops the others of this account. */
export function signalAccepted(a: { rp_id: string; user: string | null; ids: string[] } | null | undefined) {
  if (!a?.user) return
  signals().signalAllAcceptedCredentials?.({ rpId: a.rp_id, userId: a.user, allAcceptedCredentialIds: a.ids }).catch(() => undefined)
}

/** The person closed the browser's passkey window (or it timed out): not an error to show loudly. */
export const passkeyCancelled = (e: unknown) => e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'AbortError')
