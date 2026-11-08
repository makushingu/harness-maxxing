// Settings sub-navigation (route /settings/:section). Lightweight on purpose: also used by the palette.
// Sections are grouped under headings in the left column (and in the phone tabs, in the same order).
// Old ids keep working: SECTION_MOVED sends them to the section that took their content.
import { UserRound, BarChart3, Bell, FolderKanban, History, Info, ToggleRight, Blocks, Bot, Brain, Clock, DatabaseBackup, KeyRound, Mic, Plug, Send, Server, Shield, SlidersHorizontal, Trash2, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'

export type SettingsSectionId =
  | 'general' | 'profile' | 'security' | 'features'
  | 'claude' | 'memory' | 'usage' | 'keys' | 'mcp'
  | 'crons' | 'notifications' | 'telegram' | 'voice'
  | 'packs' | 'extensions' | 'backup' | 'trash'
  | 'system' | 'updates' | 'about'

export type SettingsGroupId = 'general' | 'claude' | 'automate' | 'workspace' | 'server'

export const SETTINGS_GROUPS: { id: SettingsGroupId; label: TKey }[] = [
  { id: 'general', label: 'settings.group.general' },
  { id: 'claude', label: 'settings.group.claude' },
  { id: 'automate', label: 'settings.group.automate' },
  { id: 'workspace', label: 'settings.group.workspace' },
  { id: 'server', label: 'settings.group.server' },
]

export const SETTINGS_SECTIONS: { id: SettingsSectionId; group: SettingsGroupId; label: TKey; description: TKey; icon: LucideIcon; keywords?: string }[] = [
  { id: 'general', group: 'general', label: 'settings.general', description: 'settings.general.desc', icon: SlidersHorizontal, keywords: 'theme accent language timezone density font layout install app tour tutorial presentation' },
  { id: 'profile', group: 'general', label: 'settings.profile', description: 'settings.profile.desc', icon: UserRound, keywords: 'pseudo name nickname avatar color emoji identity' },
  { id: 'security', group: 'general', label: 'settings.security', description: 'settings.security.desc', icon: Shield, keywords: 'password sign out 2fa two factor' },
  { id: 'features', group: 'general', label: 'settings.features', description: 'settings.features.desc', icon: ToggleRight, keywords: 'features pages options agents tasks team mail email infra git hud tabs maxxing enable' },
  { id: 'claude', group: 'claude', label: 'settings.claude', description: 'settings.claude.desc', icon: Bot, keywords: 'model token api key permission sign in' },
  { id: 'memory', group: 'claude', label: 'settings.memory', description: 'settings.memory.desc', icon: Brain, keywords: 'second brain memory.md clean compaction lines' },
  { id: 'usage', group: 'claude', label: 'settings.usage', description: 'settings.usage.desc', icon: BarChart3, keywords: 'stats usage quota tokens statistics plan limit cost' },
  { id: 'keys', group: 'claude', label: 'settings.keys', description: 'settings.keys.desc', icon: KeyRound, keywords: 'secrets vault env api keys' },
  { id: 'mcp', group: 'claude', label: 'settings.mcp', description: 'settings.mcp.desc', icon: Plug, keywords: 'mcp servers tools connectors oauth model context protocol' },
  { id: 'crons', group: 'automate', label: 'nav.crons', description: 'crons.description', icon: Clock, keywords: 'cron jobs schedule scheduled tasks timer recurring once history run' },
  { id: 'notifications', group: 'automate', label: 'settings.notifications', description: 'settings.notifications.desc', icon: Bell, keywords: 'notification alert sound badge pulse finished done feed' },
  { id: 'telegram', group: 'automate', label: 'settings.telegram', description: 'settings.telegram.desc', icon: Send, keywords: 'bot threads phone' },
  { id: 'voice', group: 'automate', label: 'settings.voice', description: 'settings.voice.desc', icon: Mic, keywords: 'microphone speech transcription whisper dictation audio' },
  { id: 'packs', group: 'workspace', label: 'settings.projects', description: 'settings.projects.desc', icon: FolderKanban, keywords: 'packs starter projects ecommerce affiliate creator apps second brain freelance templates import migrate hermes openclaw claude code zip memory' },
  { id: 'extensions', group: 'workspace', label: 'settings.extensions', description: 'settings.extensions.desc', icon: Blocks, keywords: 'widgets pages plugins' },
  { id: 'backup', group: 'workspace', label: 'settings.backup', description: 'settings.backup.desc', icon: DatabaseBackup, keywords: 'github memory restore' },
  { id: 'trash', group: 'workspace', label: 'settings.trash', description: 'settings.trash.desc', icon: Trash2, keywords: 'deleted restore recycle bin undo corbeille' },
  { id: 'system', group: 'server', label: 'settings.system', description: 'settings.system.desc', icon: Server, keywords: 'health services logs update version cpu ram disk' },
  { id: 'updates', group: 'server', label: 'settings.updates', description: 'settings.updates.desc', icon: History, keywords: 'changelog what is new versions release notes history' },
  { id: 'about', group: 'server', label: 'settings.about', description: 'settings.about.desc', icon: Info, keywords: 'about license licence enterprise company key business fair source support donate donation sponsor' },
]

/** Sections that moved (old links, bookmarks, notifications): old id -> where its content is now. */
export const SECTION_MOVED: Record<string, string> = {
  stats: '/settings/usage',
  license: '/settings/about',
  support: '/settings/about',
  import: '/settings/packs#import',
  docs: '/docs',
}
