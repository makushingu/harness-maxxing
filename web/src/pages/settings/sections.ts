// Settings sub-navigation (route /settings/:section). Lightweight on purpose: also used by the palette.
// The list is in display order, under the 4 headings of SETTINGS_GROUPS; the last one ("Server & about")
// starts folded. Support (donation) stays last and in the accent colour (pages/settings/index.tsx).
import { Building2, UserRound, BarChart3, Bell, FolderKanban, HandHeart, History, ToggleRight, Blocks, Bot, Brain, Clock, DatabaseBackup, FileInput, KeyRound, Mic, Plug, Send, Server, Shield, SlidersHorizontal, Trash2, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'

// 'docs' is not a section any more: /settings/docs only redirects to /docs (old links, bookmarks).
export type SettingsSectionId = 'general' | 'profile' | 'license' | 'support' | 'packs' | 'features' | 'notifications' | 'security' | 'claude' | 'stats' | 'memory' | 'crons' | 'telegram' | 'voice' | 'backup' | 'keys' | 'mcp' | 'extensions' | 'import' | 'trash' | 'system' | 'updates' | 'docs'

export type SettingsGroupId = 'essentials' | 'data' | 'tools' | 'server'

/** The headings of the list, in order. `folded`: closed until opened (or until one of its sections is shown). */
export const SETTINGS_GROUPS: { id: SettingsGroupId; label: TKey; folded?: boolean }[] = [
  { id: 'essentials', label: 'setui.essentials' },
  { id: 'data', label: 'setui.data' },
  { id: 'tools', label: 'setui.tools' },
  { id: 'server', label: 'setui.server', folded: true },
]

export const SETTINGS_SECTIONS: { id: SettingsSectionId; group: SettingsGroupId; label: TKey; description: TKey; icon: LucideIcon; keywords?: string }[] = [
  { id: 'general', group: 'essentials', label: 'settings.general', description: 'settings.general.desc', icon: SlidersHorizontal, keywords: 'theme accent language timezone density' },
  { id: 'profile', group: 'essentials', label: 'settings.profile', description: 'settings.profile.desc', icon: UserRound, keywords: 'pseudo name nickname avatar color emoji identity' },
  { id: 'claude', group: 'essentials', label: 'settings.claude', description: 'settings.claude.desc', icon: Bot, keywords: 'model token api key permission' },
  { id: 'notifications', group: 'essentials', label: 'settings.notifications', description: 'settings.notifications.desc', icon: Bell, keywords: 'notification alert sound badge pulse finished done' },
  { id: 'telegram', group: 'essentials', label: 'settings.telegram', description: 'settings.telegram.desc', icon: Send, keywords: 'bot threads' },
  { id: 'voice', group: 'essentials', label: 'settings.voice', description: 'settings.voice.desc', icon: Mic, keywords: 'microphone speech transcription whisper dictation audio' },
  { id: 'security', group: 'data', label: 'settings.security', description: 'settings.security.desc', icon: Shield, keywords: 'password sign out' },
  { id: 'backup', group: 'data', label: 'settings.backup', description: 'settings.backup.desc', icon: DatabaseBackup, keywords: 'github memory restore' },
  { id: 'trash', group: 'data', label: 'settings.trash', description: 'settings.trash.desc', icon: Trash2, keywords: 'deleted restore recycle bin undo corbeille' },
  { id: 'import', group: 'data', label: 'settings.import', description: 'settings.import.desc', icon: FileInput, keywords: 'import migrate hermes openclaw claude code zip memory' },
  { id: 'features', group: 'tools', label: 'settings.features', description: 'settings.features.desc', icon: ToggleRight, keywords: 'features options hud mirror telegram usage presentation enable experimental' },
  { id: 'crons', group: 'tools', label: 'nav.crons', description: 'crons.description', icon: Clock, keywords: 'cron jobs schedule scheduled tasks timer recurring once history run' },
  { id: 'keys', group: 'tools', label: 'settings.keys', description: 'settings.keys.desc', icon: KeyRound, keywords: 'secrets vault env api keys' },
  { id: 'mcp', group: 'tools', label: 'settings.mcp', description: 'settings.mcp.desc', icon: Plug, keywords: 'mcp servers tools connectors oauth model context protocol' },
  { id: 'extensions', group: 'tools', label: 'settings.extensions', description: 'settings.extensions.desc', icon: Blocks, keywords: 'widgets pages plugins' },
  { id: 'memory', group: 'tools', label: 'settings.memory', description: 'settings.memory.desc', icon: Brain, keywords: 'second brain memory.md clean compaction lines' },
  { id: 'packs', group: 'tools', label: 'settings.projects', description: 'settings.projects.desc', icon: FolderKanban, keywords: 'packs starter projects ecommerce affiliate creator apps second brain freelance templates' },
  { id: 'system', group: 'server', label: 'settings.system', description: 'settings.system.desc', icon: Server, keywords: 'health services logs update version' },
  { id: 'updates', group: 'server', label: 'settings.updates', description: 'settings.updates.desc', icon: History, keywords: 'changelog what is new versions release notes history' },
  { id: 'stats', group: 'server', label: 'settings.stats', description: 'settings.stats.desc', icon: BarChart3, keywords: 'usage quota tokens statistics plan limit' },
  { id: 'license', group: 'server', label: 'settings.license', description: 'settings.license.desc', icon: Building2, keywords: 'license licence enterprise company key business fair source' },
  { id: 'support', group: 'server', label: 'settings.support', description: 'settings.support.desc', icon: HandHeart, keywords: 'support donate donation sponsor fund contribute help the project' },
]
