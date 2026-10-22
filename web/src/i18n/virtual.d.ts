// Built by `i18nSplit` (vite.config.ts): for each language, a loader per dictionary chunk (core + groups.ts).
declare module 'virtual:i18n-loaders' {
  export const loaders: Record<string, Record<string, () => Promise<{ default: Record<string, string> }>>>
}
