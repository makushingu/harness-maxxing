// Dictionary groups. A key's namespace is its first segment (`infra.site.add` -> `infra`). Every namespace listed
// here leaves the core dictionary: its group is a separate chunk per language (built by `i18nSplit` in
// vite.config.ts), loaded with the routes that declare it in routes.tsx, else on the first key asked from it.
// A namespace not listed stays in the core, which main.tsx waits for before the first render: list here only
// namespaces the shell (sidebar, tab bar, palette, dialogs) and the dashboard do not show.
export const GROUPS = {
  settings: [
    'mcp', 'system', 'stats', 'keys', 'memory', 'trash', 'features', 'security', 'profile', 'fonts', 'accent',
    'density', 'tint', 'backup', 'import', 'telegram', 'packs', 'pc', 'license', 'register', 'cdef',
    'keyfiles', 'about', 'appearance', 'skills', 'emoji',
  ],
  auth: ['onb', 'setup', 'login', 'pw', 'twofa'],
  infra: ['infra'],
  git: ['git'],
  team: ['team'],
  agents: ['agents', 'groups'],
  mail: ['mail'],
  tasks: ['tasks', 'crons'],
  files: ['files', 'viewer'],
  // the media player: on the first player shown (a conversation shows one only for an audio file or in the viewer)
  media: ['media'],
  // the project / topic cards of a session header: loaded on the first hover
  where: ['where'],
  show: ['show'],
  feedback: ['feedback'],
  // Maxxing mode (beta, off by default): its texts load only once its controls show
  maxxing: ['maxxing'],
  // dragging content from one session into another: loaded when a drag starts
  drag: ['drag'],
  // a pasted text that became a file: loaded on that paste
  paste: ['paste'],
  // extra words of the Settings sections for the command palette: loaded on its first search
  skw: ['skw'],
  // the guided tour: loaded with its chunk (tour/Tour.tsx); its entry points (menu, palette) use help.*
  tour: ['tour'],
  // the composer's / and @ menus and the intelligence (effort) level: loaded on their first text asked
  composer: ['slash', 'mention', 'effort'],
} as const satisfies Record<string, readonly string[]>

export type Group = keyof typeof GROUPS
