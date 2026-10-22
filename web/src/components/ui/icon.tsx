// Icon helpers.
// - <NamedIcon name="calendar-days"/>: renders a lucide icon from its kebab-case name (widgets and
//   extensions declare icons by name). Only the curated set below is bundled (no 1 600-chunk build);
//   unknown names fall back to a puzzle piece. Add names here when needed.
// - <Avatar label="Acme"/>: initials avatar with a stable hue per label.
import * as React from 'react'
import * as AvatarPrimitive from '@radix-ui/react-avatar'
import {
  Activity, AlarmClock, Archive, BarChart3, Bell, Bot, Brain, Briefcase, Calendar, CalendarClock, CalendarDays, ChartLine, ChartPie,
  CheckCircle2, CircleDollarSign, Clock, Cloud, Code2, Coins, Cpu, Database, DollarSign, Download, Euro, Eye, File,
  FileText, Flag, Folder, Gauge, GitBranch, Globe, Hammer, HardDrive, Heart, Home, Inbox, Key, Layers,
  LayoutDashboard, LayoutGrid, Link, List, ListChecks, Lock, Mail, Map, MemoryStick, MessageSquare, MessagesSquare,
  Mic, Monitor, Moon, Network, Newspaper, Package, PenLine, Puzzle, Receipt, Rocket, Rss, Search, Send, Server,
  Settings, Shield, ShoppingBag, ShoppingCart, Sparkles, Star, Store, Sun, Tag, Target, Terminal, Timer, TrendingUp,
  Trophy, Truck, Upload, User, Users, Wallet, Wifi, Wrench, Zap, DatabaseBackup, Radar, NotebookPen, TriangleAlert,
  BookOpen, CloudUpload, ChartColumn, Notebook, Bug, Image, Video, Music, Handshake, Clapperboard, GraduationCap, FolderPlus,
  CreditCard, AppWindow, ArrowRight, ExternalLink, Info, Plus, Check, X, Pencil, Trash, Funnel, RefreshCw, Phone, MapPin,
  Building, MessageCircle, Lightbulb, FilePlus, Contact, WandSparkles, Gamepad2, StickyNote, type LucideIcon,
} from 'lucide-react'
import { cn } from '@/lib/utils'

export const ICONS: Record<string, LucideIcon> = {
  activity: Activity, 'alarm-clock': AlarmClock, archive: Archive, 'bar-chart': BarChart3, 'bar-chart-3': BarChart3,
  bell: Bell, bot: Bot, brain: Brain, briefcase: Briefcase, calendar: Calendar, 'calendar-clock': CalendarClock, 'calendar-days': CalendarDays,
  'chart-line': ChartLine, 'chart-pie': ChartPie, 'check-circle': CheckCircle2, 'circle-dollar-sign': CircleDollarSign,
  clock: Clock, cloud: Cloud, code: Code2, coins: Coins, cpu: Cpu, database: Database, 'dollar-sign': DollarSign,
  download: Download, euro: Euro, eye: Eye, file: File, 'file-text': FileText, flag: Flag, folder: Folder, gauge: Gauge,
  'git-branch': GitBranch, globe: Globe, hammer: Hammer, 'hard-drive': HardDrive, heart: Heart,
  home: Home, inbox: Inbox, key: Key, layers: Layers, 'layout-dashboard': LayoutDashboard, 'layout-grid': LayoutGrid,
  link: Link, list: List, 'list-checks': ListChecks, lock: Lock, mail: Mail, map: Map, 'memory-stick': MemoryStick,
  'message-square': MessageSquare, 'messages-square': MessagesSquare, mic: Mic, monitor: Monitor, moon: Moon,
  network: Network, newspaper: Newspaper, package: Package, 'pen-line': PenLine, puzzle: Puzzle, receipt: Receipt,
  rocket: Rocket, rss: Rss, search: Search, send: Send, server: Server, settings: Settings, shield: Shield,
  'shopping-bag': ShoppingBag, 'shopping-cart': ShoppingCart, sparkles: Sparkles, star: Star, store: Store, sun: Sun,
  tag: Tag, target: Target, terminal: Terminal, timer: Timer, 'trending-up': TrendingUp, trophy: Trophy, truck: Truck,
  upload: Upload, user: User, users: Users, wallet: Wallet, wifi: Wifi, wrench: Wrench, zap: Zap,
  'database-backup': DatabaseBackup, radar: Radar, 'notebook-pen': NotebookPen, 'triangle-alert': TriangleAlert,
  'book-open': BookOpen, 'cloud-upload': CloudUpload, 'chart-column': ChartColumn, notebook: Notebook, bug: Bug,
  image: Image, video: Video, music: Music, handshake: Handshake, clapperboard: Clapperboard, 'graduation-cap': GraduationCap,
  'folder-plus': FolderPlus, 'credit-card': CreditCard, 'app-window': AppWindow, 'arrow-right': ArrowRight,
  'external-link': ExternalLink, info: Info, plus: Plus, check: Check, x: X, pencil: Pencil, trash: Trash, filter: Funnel,
  'refresh-cw': RefreshCw, phone: Phone, 'map-pin': MapPin, building: Building, 'message-circle': MessageCircle,
  lightbulb: Lightbulb, 'file-plus': FilePlus, contact: Contact, 'wand-sparkles': WandSparkles,
  'gamepad-2': Gamepad2, 'sticky-note': StickyNote,
}

export function NamedIcon({ name, className, ...props }: { name?: string | null; className?: string } & React.SVGProps<SVGSVGElement>) {
  const Cmp = (name && ICONS[name.toLowerCase()]) || Puzzle
  return <Cmp className={cn('size-4', className)} aria-hidden {...(props as object)} />
}

function hue(s: string) {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
  return h
}

export function initials(label: string) {
  const parts = label.replace(/[-_]+/g, ' ').trim().split(/\s+/)
  return ((parts[0]?.[0] || '') + (parts[1]?.[0] || parts[0]?.[1] || '')).toUpperCase() || '?'
}

export function Avatar({ label, src, className }: { label: string; src?: string; className?: string }) {
  const h = hue(label)
  return (
    <AvatarPrimitive.Root className={cn('relative inline-flex size-8 shrink-0 overflow-hidden rounded-full select-none', className)}>
      {src && <AvatarPrimitive.Image src={src} alt="" className="size-full object-cover" />}
      <AvatarPrimitive.Fallback
        className="flex size-full items-center justify-center text-[11px] font-semibold"
        style={{ background: `oklch(0.55 0.12 ${h} / 0.22)`, color: `oklch(0.75 0.12 ${h})` }}
      >
        {initials(label)}
      </AvatarPrimitive.Fallback>
    </AvatarPrimitive.Root>
  )
}
