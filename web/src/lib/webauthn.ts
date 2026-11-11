/** Passkeys / security keys (WebAuthn): the server's JSON options (base64url) <-> the browser API (ArrayBuffer).
 *  Written by hand: parseCreationOptionsFromJSON / toJSON are too recent in Safari and Firefox. */

type Descriptor = { id: string; type: 'public-key'; transports?: string[] }
export type PublicKeyCredentialCreationOptionsJSON = {
  rp: { id?: string; name: string }
  user: { id: string; name: string; displayName: string }
  challenge: string
  pubKeyCredParams: { type: 'public-key'; alg: number }[]
  timeout?: number
  excludeCredentials?: Descriptor[]
  authenticatorSelection?: AuthenticatorSelectionCriteria
  attestation?: AttestationConveyancePreference
}
export type PublicKeyCredentialRequestOptionsJSON = {
  challenge: string
  timeout?: number
  rpId?: string
  allowCredentials?: Descriptor[]
  userVerification?: UserVerificationRequirement
}

function fromB64(s: string): ArrayBuffer {
  const b = atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4))
  const out = new Uint8Array(b.length)
  for (let i = 0; i < b.length; i++) out[i] = b.charCodeAt(i)
  return out.buffer
}

function toB64(buf: ArrayBuffer | null): string | null {
  if (!buf) return null
  let s = ''
  for (const byte of new Uint8Array(buf)) s += String.fromCharCode(byte)
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

const descriptors = (list?: Descriptor[]): PublicKeyCredentialDescriptor[] | undefined =>
  list?.map((d) => ({ type: 'public-key', id: fromB64(d.id), transports: d.transports as AuthenticatorTransport[] | undefined }))

/** WebAuthn works on HTTPS pages (and localhost) of a browser that has it. */
export function passkeysSupported(): boolean {
  return typeof window !== 'undefined' && window.isSecureContext && typeof window.PublicKeyCredential === 'function'
}

/** Creates a passkey: the JSON the server checks. Throws a DOMException when cancelled (NotAllowedError). */
export async function createPasskey(o: PublicKeyCredentialCreationOptionsJSON): Promise<unknown> {
  const cred = (await navigator.credentials.create({
    publicKey: {
      ...o,
      challenge: fromB64(o.challenge),
      user: { ...o.user, id: fromB64(o.user.id) },
      excludeCredentials: descriptors(o.excludeCredentials),
    },
  })) as PublicKeyCredential | null
  if (!cred) throw new DOMException('No passkey', 'NotAllowedError')
  const r = cred.response as AuthenticatorAttestationResponse
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: {
      clientDataJSON: toB64(r.clientDataJSON),
      attestationObject: toB64(r.attestationObject),
      transports: typeof r.getTransports === 'function' ? r.getTransports() : [],
    },
  }
}

/** Signs the server's challenge with a passkey of this address: the JSON the server checks. */
export async function signWithPasskey(o: PublicKeyCredentialRequestOptionsJSON): Promise<unknown> {
  const cred = (await navigator.credentials.get({
    publicKey: { ...o, challenge: fromB64(o.challenge), allowCredentials: descriptors(o.allowCredentials) },
  })) as PublicKeyCredential | null
  if (!cred) throw new DOMException('No passkey', 'NotAllowedError')
  const r = cred.response as AuthenticatorAssertionResponse
  return {
    id: cred.id,
    rawId: toB64(cred.rawId),
    type: cred.type,
    authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
    clientExtensionResults: cred.getClientExtensionResults(),
    response: {
      clientDataJSON: toB64(r.clientDataJSON),
      authenticatorData: toB64(r.authenticatorData),
      signature: toB64(r.signature),
      userHandle: toB64(r.userHandle),
    },
  }
}

/** A cancelled or timed-out browser prompt (not an error worth a message). */
export const passkeyCancelled = (e: unknown) => e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'AbortError')
