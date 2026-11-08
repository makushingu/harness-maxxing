// Settings sub-navigation (route /settings/:section). Lightweight on purpose: also used by the palette.
// Sections are grouped under headings in the left column (and in the phone tabs, in the same order).
// Old ids keep working: SECTION_MOVED sends them to the section that took their content.
import { UserRound, BarChart3, Bell, FileInput, History, Info, LayoutGrid, LayoutTemplate, ToggleRight, Bot, Brain, Clock, DatabaseBackup, HandHeart, KeyRound, Mic, Palette, PanelsTopLeft, Plug, Send, Server, Shield, SlidersHorizontal, Sparkles, Trash2, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'

export type SettingsSectionId =
  | 'general' | 'appearance' | 'profile' | 'security' | 'features'
  | 'claude' | 'memory' | 'skills' | 'mcp' | 'keys' | 'usage'
  | 'crons' | 'notifications' | 'telegram' | 'voice'
  | 'widgets' | 'pages'
  | 'templates' | 'import' | 'backup' | 'trash'
  | 'system' | 'updates' | 'about' | 'support'

export type SettingsGroupId = 'general' | 'claude' | 'automate' | 'extensions' | 'workspace' | 'server'

export const SETTINGS_GROUPS: { id: SettingsGroupId; label: TKey }[] = [
  { id: 'general', label: 'settings.group.general' },
  { id: 'claude', label: 'settings.group.claude' },
  { id: 'automate', label: 'settings.group.automate' },
  { id: 'extensions', label: 'settings.group.extensions' },
  { id: 'workspace', label: 'settings.group.workspace' },
  { id: 'server', label: 'settings.group.server' },
]

export const SETTINGS_SECTIONS: { id: SettingsSectionId; group: SettingsGroupId; label: TKey; description: TKey; icon: LucideIcon; keywords?: string }[] = [
  { id: 'general', group: 'general', label: 'settings.general', description: 'settings.general.desc', icon: SlidersHorizontal, keywords: 'language timezone region install app phone home screen tour tutorial help' },
  { id: 'appearance', group: 'general', label: 'settings.appearance', description: 'settings.appearance.desc', icon: Palette, keywords: 'theme dark light accent color background tint density compact font mono layout touch phone first screen look' },
  { id: 'profile', group: 'general', label: 'settings.profile', description: 'settings.profile.desc', icon: UserRound, keywords: 'pseudo name nickname avatar color emoji identity stay in touch contact news email register counter' },
  { id: 'security', group: 'general', label: 'settings.security', description: 'settings.security.desc', icon: Shield, keywords: 'password sign out 2fa two factor presentation privacy blur hide' },
  { id: 'features', group: 'general', label: 'settings.features', description: 'settings.features.desc', icon: ToggleRight, keywords: 'features pages options agents tasks team mail email infra git hud tabs maxxing result line cost enable' },
  { id: 'claude', group: 'claude', label: 'settings.claude', description: 'settings.claude.desc', icon: Bot, keywords: 'model token api key permission sign in' },
  { id: 'memory', group: 'claude', label: 'settings.memory', description: 'settings.memory.desc', icon: Brain, keywords: 'second brain memory.md clean compaction lines' },
  { id: 'skills', group: 'claude', label: 'settings.skills', description: 'settings.skills.desc', icon: Sparkles, keywords: 'skills skill.md recipes commands slash abilities' },
  { id: 'mcp', group: 'claude', label: 'settings.mcp', description: 'settings.mcp.desc', icon: Plug, keywords: 'mcp servers tools connectors oauth model context protocol' },
  { id: 'keys', group: 'claude', label: 'settings.keys', description: 'settings.keys.desc', icon: KeyRound, keywords: 'secrets vault env api keys' },
  { id: 'usage', group: 'claude', label: 'settings.usage', description: 'settings.usage.desc', icon: BarChart3, keywords: 'stats usage quota tokens statistics plan limit cost' },
  { id: 'crons', group: 'automate', label: 'nav.crons', description: 'crons.description', icon: Clock, keywords: 'cron jobs schedule scheduled tasks timer recurring once history run' },
  { id: 'notifications', group: 'automate', label: 'settings.notifications', description: 'settings.notifications.desc', icon: Bell, keywords: 'notification alert sound badge pulse finished done feed' },
  { id: 'telegram', group: 'automate', label: 'settings.telegram', description: 'settings.telegram.desc', icon: Send, keywords: 'bot threads phone' },
  { id: 'voice', group: 'automate', label: 'settings.voice', description: 'settings.voice.desc', icon: Mic, keywords: 'microphone speech transcription whisper dictation audio' },
  { id: 'widgets', group: 'extensions', label: 'settings.widgets', description: 'settings.widgets.desc', icon: LayoutGrid, keywords: 'widgets dashboard cards extensions game' },
  { id: 'pages', group: 'extensions', label: 'settings.pages', description: 'settings.pages.desc', icon: PanelsTopLeft, keywords: 'pages extensions sidebar pin office view plugins' },
  { id: 'templates', group: 'workspace', label: 'settings.templates', description: 'settings.templates.desc', icon: LayoutTemplate, keywords: 'templates starter packs projects topics ecommerce affiliate creator apps second brain freelance new project' },
  { id: 'import', group: 'workspace', label: 'settings.import', description: 'settings.import.desc', icon: FileInput, keywords: 'import migrate hermes openclaw claude code zip memory data restore agent' },
  { id: 'backup', group: 'workspace', label: 'settings.backup', description: 'settings.backup.desc', icon: DatabaseBackup, keywords: 'github memory restore' },
  { id: 'trash', group: 'workspace', label: 'settings.trash', description: 'settings.trash.desc', icon: Trash2, keywords: 'deleted restore recycle bin undo corbeille' },
  { id: 'system', group: 'server', label: 'settings.system', description: 'settings.system.desc', icon: Server, keywords: 'health services logs cpu ram disk public address url files root' },
  { id: 'updates', group: 'server', label: 'settings.updates', description: 'settings.updates.desc', icon: History, keywords: 'update upgrade version check automatic changelog what is new release notes history' },
  { id: 'about', group: 'server', label: 'settings.about', description: 'settings.about.desc', icon: Info, keywords: 'about license licence enterprise company key business fair source docs github community' },
  { id: 'support', group: 'server', label: 'settings.support', description: 'settings.support.desc', icon: HandHeart, keywords: 'support donate donation sponsor bitcoin lightning hide donate buttons' },
]

/** Sections that moved (old links, bookmarks, notifications): old id -> where its content is now. */
export const SECTION_MOVED: Record<string, string> = {
  stats: '/settings/usage',
  license: '/settings/about',
  docs: '/docs',
  packs: '/settings/templates',
  projects: '/settings/templates',
  extensions: '/settings/widgets',
}
