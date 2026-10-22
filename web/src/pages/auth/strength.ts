/** Minimum length of a new password (= server security.MIN_PASSWORD). */
export const MIN_PASSWORD = 12

/** Rough password strength 0..4 (length + character variety). Hint only, never blocks beyond the minimum. */
export function passwordScore(pw: string): 0 | 1 | 2 | 3 | 4 {
  if (!pw) return 0
  let variety = 0
  if (/[a-z]/.test(pw)) variety++
  if (/[A-Z]/.test(pw)) variety++
  if (/\d/.test(pw)) variety++
  if (/[^A-Za-z0-9]/.test(pw)) variety++
  if (pw.length < MIN_PASSWORD) return 1
  let s = 1
  if (pw.length >= 16) s++
  if (pw.length >= 20) s++
  if (variety >= 3) s++
  if (/^(.)\1+$/.test(pw) || /^(password|motdepasse|12345678|azerty|qwerty)/i.test(pw)) s = 1
  return Math.min(4, s) as 0 | 1 | 2 | 3 | 4
}
