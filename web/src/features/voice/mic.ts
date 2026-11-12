// The microphone that records on this device: the browser's default one, unless another is chosen in
// Settings -> Voice. The choice stays in this browser (a microphone belongs to the device, not to the server).
import * as React from 'react'

const KEY = 'mx-voice-mic'
const AUDIO: MediaTrackConstraints = { echoCancellation: true, noiseSuppression: true, autoGainControl: true }

/** Id of the chosen microphone ('' = the browser's default one). */
export function micId(): string {
  try {
    return localStorage.getItem(KEY) || ''
  } catch {
    return ''
  }
}

export function setMicId(id: string) {
  try {
    if (id) localStorage.setItem(KEY, id)
    else localStorage.removeItem(KEY)
  } catch {
    /* storage refused (private mode): the default microphone */
  }
}

/** Opens the chosen microphone; when it is not there any more (unplugged, id forgotten by the browser), the default
 *  one - the choice is kept for when it comes back. */
export async function openMic(): Promise<MediaStream> {
  const id = micId()
  if (id) {
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: { ...AUDIO, deviceId: { exact: id } } })
    } catch (e) {
      const name = (e as Error)?.name
      if (name !== 'OverconstrainedError' && name !== 'NotFoundError') throw e
    }
  }
  return navigator.mediaDevices.getUserMedia({ audio: AUDIO })
}

export interface MicDevice {
  id: string
  label: string
}

/** The microphones of this device. A browser gives their names only once the microphone was allowed: `named` is
 *  false until then, and `ask()` asks for it. */
export function useMics() {
  const [mics, setMics] = React.useState<MicDevice[]>([])
  const [named, setNamed] = React.useState(true)
  const load = React.useCallback(async () => {
    try {
      const all = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput')
      // Chrome also lists `default` and `communications`: other names of one of the microphones below
      setMics(all.filter((d) => d.deviceId && d.deviceId !== 'default' && d.deviceId !== 'communications').map((d) => ({ id: d.deviceId, label: d.label })))
      setNamed(!all.length || all.some((d) => d.label))
    } catch {
      setMics([])
    }
  }, [])
  React.useEffect(() => {
    const media = navigator.mediaDevices
    if (!media?.enumerateDevices) return
    void load()
    media.addEventListener?.('devicechange', load)
    // allowed elsewhere on the page (the record test, the mic button): the names are there now
    let perm: PermissionStatus | undefined
    navigator.permissions
      ?.query({ name: 'microphone' as PermissionName })
      .then((p) => {
        perm = p
        p.addEventListener('change', load)
      })
      .catch(() => {})
    return () => {
      media.removeEventListener?.('devicechange', load)
      perm?.removeEventListener('change', load)
    }
  }, [load])
  const ask = React.useCallback(async () => {
    const s = await navigator.mediaDevices.getUserMedia({ audio: true })
    try {
      await load() // while the microphone is open: some browsers name the devices only then
    } finally {
      s.getTracks().forEach((tr) => tr.stop())
    }
  }, [load])
  return { mics, named, ask }
}
