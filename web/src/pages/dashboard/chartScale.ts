/** The value scale of a dashboard chart (charts.tsx): a round top, and a bottom under 0 only for real negatives. */
export function niceMax(v: number) {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
}

/** A point's value as a number: a number, or a number written as text ("40", what a shell or jq extension often
 * sends); anything else (null, "", "abc") is NaN, a point without a value. */
export function chartValue(v: unknown): number {
  if (typeof v === 'number') return v
  if (typeof v === 'string' && v.trim() !== '') return Number(v)
  return NaN
}

export function chartScale(values: unknown[]): { min: number; max: number; ticks: number[] } {
  // a missing or text value is not drawn; a loop, not Math.max(...values): a long series overflows the call stack
  let hi = 0
  let lo = 0
  for (const raw of values) {
    const v = chartValue(raw)
    if (!Number.isFinite(v)) continue
    if (v > hi) hi = v
    if (v < lo) lo = v
  }
  const max = niceMax(hi)
  // negative values: the scale goes below 0, the bars hang under it; a value just under 0 next to large ones (float
  // noise, -0.001 next to 50) keeps the scale at 0, where it is drawn: no "-0" label stacked on the "0" one
  const min = lo < 0 && -lo > max / 100 ? -niceMax(-lo) : 0
  return { min, max, ticks: min < 0 ? [min, 0, max] : [0, max / 2, max] }
}
