/** The value scale of a dashboard chart (charts.tsx): a round top, and a bottom under 0 only for real negatives. */
export function niceMax(v: number) {
  if (v <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(v))
  const n = v / p
  return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p
}

export function chartScale(values: number[]): { min: number; max: number; ticks: number[] } {
  const max = niceMax(Math.max(0, ...values))
  const lo = Math.min(0, ...values)
  // negative values: the scale goes below 0, the bars hang under it; a value just under 0 next to large ones (float
  // noise, -0.001 next to 50) keeps the scale at 0, where it is drawn: no "-0" label stacked on the "0" one
  const min = lo < 0 && -lo > max / 100 ? -niceMax(-lo) : 0
  return { min, max, ticks: min < 0 ? [min, 0, max] : [0, max / 2, max] }
}
