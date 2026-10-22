export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

let cache: { value: string; label: string; hint: string }[] | null = null
export const timezoneLabel = (z: string) => z.replace(/_/g, ' ')

/** All IANA zones with their current UTC offset (~420 Intl formatters: build it only when the list is shown). */
export function timezoneOptions() {
  if (cache) return cache
  let zones: string[] = []
  try {
    zones = (Intl as unknown as { supportedValuesOf: (k: string) => string[] }).supportedValuesOf('timeZone')
  } catch {
    zones = ['UTC', 'Europe/London', 'Europe/Paris', 'America/New_York', 'America/Los_Angeles', 'Asia/Tokyo']
  }
  if (!zones.includes('UTC')) zones = ['UTC', ...zones]
  const now = new Date()
  cache = zones.map((z) => {
    let hint = ''
    try {
      hint = new Intl.DateTimeFormat('en', { timeZone: z, timeZoneName: 'shortOffset' }).formatToParts(now).find((p) => p.type === 'timeZoneName')?.value || ''
    } catch {
      /* ignore */
    }
    return { value: z, label: timezoneLabel(z), hint }
  })
  return cache
}
