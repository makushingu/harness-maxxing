// Dictionary groups. A key's namespace is its first segment (`infra.site.add` -> `infra`). Every namespace listed
// here leaves the core dictionary: its group is a separate chunk per language (built by `i18nSplit` in
// vite.config.ts), loaded with the routes that declare it in routes.tsx, else on the first key asked from it.
// A namespace not listed stays in the core, which main.tsx waits for before the first render: list here only
// namespaces the shell (sidebar, tab bar, palette, dialogs) and the dashboard do not show.
export const GROUPS = {
  settings: [
    'mcp', 'system', 'stats', 'keys', 'memory', 'trash', 'features', 'security', 'profile', 'fonts', 'accent',
    'density', 'tint', 'backup', 'import', 'telegram', 'packs', 'pc', 'license', 'register',
  ],
  auth: ['onb', 'setup', 'login', 'pw', 'twofa'],
  infra: ['infra'],
  git: ['git'],
  tasks: ['tasks', 'crons'],
  files: ['files', 'viewer', 'media'],
  show: ['show'],
} as const satisfies Record<string, readonly string[]>

export type Group = keyof typeof GROUPS
