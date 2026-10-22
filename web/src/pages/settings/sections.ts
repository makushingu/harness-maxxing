// Settings sub-navigation (route /settings/:section). Lightweight on purpose: also used by the palette.
import { Building2, UserRound, BarChart3, Bell, FolderKanban, History, ToggleRight, Blocks, BookOpen, Bot, Brain, DatabaseBackup, FileInput, KeyRound, Mic, Plug, Send, Server, Shield, SlidersHorizontal, Trash2, type LucideIcon } from 'lucide-react'
import type { TKey } from '@/i18n'

export type SettingsSectionId = 'general' | 'profile' | 'license' | 'packs' | 'features' | 'notifications' | 'security' | 'claude' | 'stats' | 'memory' | 'telegram' | 'voice' | 'backup' | 'keys' | 'mcp' | 'extensions' | 'import' | 'trash' | 'system' | 'updates' | 'docs'

export const SETTINGS_SECTIONS: { id: SettingsSectionId; label: TKey; description: TKey; icon: LucideIcon; keywords?: string }[] = [
  { id: 'general', label: 'settings.general', description: 'settings.general.desc', icon: SlidersHorizontal, keywords: 'theme accent language timezone density' },
  { id: 'profile', label: 'settings.profile', description: 'settings.profile.desc', icon: UserRound, keywords: 'pseudo name nickname avatar color emoji identity' },
  { id: 'license', label: 'settings.license', description: 'settings.license.desc', icon: Building2, keywords: 'license licence enterprise company key business fair source' },
  { id: 'system', label: 'settings.system', description: 'settings.system.desc', icon: Server, keywords: 'health services logs update version' },
  { id: 'updates', label: 'settings.updates', description: 'settings.updates.desc', icon: History, keywords: 'changelog what is new versions release notes history' },
  { id: 'stats', label: 'settings.stats', description: 'settings.stats.desc', icon: BarChart3, keywords: 'usage quota tokens statistics plan limit' },
  { id: 'features', label: 'settings.features', description: 'settings.features.desc', icon: ToggleRight, keywords: 'features options hud mirror telegram usage presentation enable experimental' },
  { id: 'notifications', label: 'settings.notifications', description: 'settings.notifications.desc', icon: Bell, keywords: 'notification alert sound badge pulse finished done' },
  { id: 'security', label: 'settings.security', description: 'settings.security.desc', icon: Shield, keywords: 'password sign out' },
  { id: 'claude', label: 'settings.claude', description: 'settings.claude.desc', icon: Bot, keywords: 'model token api key permission' },
  { id: 'memory', label: 'settings.memory', description: 'settings.memory.desc', icon: Brain, keywords: 'second brain memory.md clean compaction lines' },
  { id: 'telegram', label: 'settings.telegram', description: 'settings.telegram.desc', icon: Send, keywords: 'bot threads' },
  { id: 'voice', label: 'settings.voice', description: 'settings.voice.desc', icon: Mic, keywords: 'microphone speech transcription whisper dictation audio' },
  { id: 'backup', label: 'settings.backup', description: 'settings.backup.desc', icon: DatabaseBackup, keywords: 'github memory restore' },
  { id: 'keys', label: 'settings.keys', description: 'settings.keys.desc', icon: KeyRound, keywords: 'secrets vault env api keys' },
  { id: 'mcp', label: 'settings.mcp', description: 'settings.mcp.desc', icon: Plug, keywords: 'mcp servers tools connectors oauth model context protocol' },
  { id: 'extensions', label: 'settings.extensions', description: 'settings.extensions.desc', icon: Blocks, keywords: 'widgets pages plugins' },
  { id: 'import', label: 'settings.import', description: 'settings.import.desc', icon: FileInput, keywords: 'import migrate hermes openclaw claude code zip memory' },
  { id: 'trash', label: 'settings.trash', description: 'settings.trash.desc', icon: Trash2, keywords: 'deleted restore recycle bin undo corbeille' },
  { id: 'packs', label: 'settings.projects', description: 'settings.projects.desc', icon: FolderKanban, keywords: 'packs starter projects ecommerce affiliate creator apps second brain freelance templates' },
  { id: 'docs', label: 'settings.docs', description: 'settings.docs.desc', icon: BookOpen, keywords: 'help documentation guide' },
]
