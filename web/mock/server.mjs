#!/usr/bin/env node
// Harness Maxxing v2 — dev MOCK backend (zero dependencies, Node 22, ESM).
//
//   node mock/server.mjs                       # port 8809, scenario "ready"
//   MOCK_PORT=8899 MOCK_SCENARIO=setup node mock/server.mjs
//   curl -X POST localhost:8809/__mock/scenario -d '{"name":"login"}'   # reset state at runtime
//   curl -X POST localhost:8809/__mock/bus -d '{"topics":["sessions","workspace"]}'   # emit a bus event
//
// Implements every endpoint of docs/dev/API.md with in-memory state and fake, product-neutral data.
// Serves the built SPA from ../dist (web/dist). Scenarios: setup | login | onboarding | ready | maxxing.
// maxxing: 30 more sessions that keep finishing at random (Maxxing mode); MOCK_PASSWORD=... asks for that password.

import http from 'node:http'
import fs from 'node:fs'
import path from 'node:path'
import crypto from 'node:crypto'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DIST = process.env.MOCK_DIST || path.resolve(__dirname, '../dist')
const PORT = Number(process.env.MOCK_PORT || 8809)
const HOST = '127.0.0.1'
const ROOT = '/root/maxxing'
const VERSION = '2.0.0'
const SETUP_TOKEN = 'dev-token'
const DEFAULT_PASSWORD = 'password123'
const SCENARIOS = ['setup', 'login', 'onboarding', 'ready', 'maxxing']
const MOCK_PASSWORD = process.env.MOCK_PASSWORD || ''

/* =================================================================== helpers */
const now = () => Date.now() / 1000
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const uuid = () => crypto.randomUUID()
const rid = (p) => `${p}_${crypto.randomBytes(4).toString('hex')}`
const sha = () => crypto.randomBytes(20).toString('hex')
const clone = (o) => JSON.parse(JSON.stringify(o))
const SLUG = /^[a-z0-9][a-z0-9-]{0,47}$/
const MIN = 60, HOUR = 3600, DAY = 86400

function rng(seed) { // mulberry32, deterministic fake data
  return () => {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

class HttpError extends Error {
  constructor(status, error, message) { super(message || error); this.status = status; this.error = error }
}
const fail = (status, error, message) => { throw new HttpError(status, error, message || error.replace(/_/g, ' ')) }
const RAW = Symbol('raw') // handler wrote the response itself

const MIME = {
  '.md': 'text/markdown', '.txt': 'text/plain', '.json': 'application/json', '.js': 'text/javascript', '.mjs': 'text/javascript',
  '.ts': 'text/x-typescript', '.tsx': 'text/x-typescript', '.css': 'text/css', '.html': 'text/html', '.py': 'text/x-python',
  '.sh': 'text/x-shellscript', '.csv': 'text/csv', '.yaml': 'text/yaml', '.yml': 'text/yaml', '.toml': 'text/plain',
  '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp', '.gif': 'image/gif', '.svg': 'image/svg+xml',
  '.mp4': 'video/mp4', '.pdf': 'application/pdf', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.woff': 'font/woff', '.map': 'application/json',
  '.webmanifest': 'application/manifest+json',
}
const mimeOf = (p) => MIME[path.extname(p).toLowerCase()] || (path.basename(p) === 'Caddyfile' ? 'text/plain' : 'application/octet-stream')
const isText = (m) => m.startsWith('text/') || m === 'application/json' || m === 'image/svg+xml'

/* =================================================================== static data */
const MODELS = [
  { id: 'claude-opus-5-5', label: 'Opus 5.5' },
  { id: 'claude-sonnet-5-5', label: 'Sonnet 5.5' },
  { id: 'claude-haiku-4-5-20251001', label: 'Haiku 4.5' },
  { id: 'claude-fable-5-1', label: 'Fable 5.1' },
]

const WORKSPACE = [
  { name: 'acme', description: 'Acme Inc. — company website, blog and SEO', topics: [
    ['blog', 'Weekly articles for the Acme blog'], ['website', 'Marketing site (Astro + Tailwind)'], ['seo', 'Keywords, audits and monthly reports']] },
  { name: 'personal', description: 'Personal notes and finances', topics: [
    ['notes', 'Ideas, reading notes and journal'], ['finance', 'Budget and expense tracking']] },
  { name: 'ops', description: 'Server and infrastructure', topics: [['server', 'VPS maintenance, Caddy, backups']] },
]
const projPath = (p) => `projects/${p}`
const topicPath = (p, t) => `projects/${p}/topics/${t}`

const SECRET_SEED = [
  ['OPENAI_API_KEY', 'Image generation for blog covers', true, 'sk-proj-4f9a1c7e2b8d6a3f0e5c9b1d7a2e8f4c'],
  ['GITHUB_TOKEN', 'Fine-grained PAT — acme/website contents RW', true, 'ghp_9Xk2LmQ7vR4tY8wZ1aB3cD5eF6gH0jK2'],
  ['STRIPE_SECRET_KEY', 'Shop sales widget (read-only restricted key)', false, 'rk_live_51Hx9aKd8fJ2mQ0pL7vN3sT6wY'],
  ['CLOUDFLARE_API_TOKEN', 'DNS edit on example.com zone', true, 'cf_7Hq2Zm9Kx4Lp1Vb8Nc3Rt6Ws0Yd5'],
  ['SMTP_PASSWORD', 'Transactional mail (newsletter@example.com)', false, 'smtp-Pz8qW3eR5tY7uI9oP1aS'],
]

const SERVICES = [
  ['claude-maxxing', 'Harness Maxxing'], ['caddy', 'Caddy web server'], ['tailscaled', 'Tailscale'], ['cron', 'Cron daemon'],
]

/* =================================================================== state */
let S = null
let GEN = 0 // bumped on reset; async timers check it

function buildState(scenario) {
  const t = now()
  const ready = scenario === 'ready' || scenario === 'login' || scenario === 'maxxing'
  const st = {
    scenario,
    bootAt: t - 12 * DAY - 3 * HOUR,
    setup_required: scenario === 'setup',
    password: scenario === 'setup' ? null : scenario === 'maxxing' && MOCK_PASSWORD ? MOCK_PASSWORD : DEFAULT_PASSWORD,
    autoAuth: scenario === 'onboarding' || scenario === 'ready' || (scenario === 'maxxing' && !MOCK_PASSWORD),
    tokens: new Set(),
    loginFails: [], // timestamps
    lockUntil: 0,
    onboarding_completed: ready,
    settings: { timezone: 'Europe/Paris', language: 'en', public_url: 'https://ui.example.com', files_root: ROOT, presentation_default: false, usage_widget: false, maxxing_mode: false, memory_max_lines: 200, donation_hidden: false },
    claude: {
      installed: true, version: '2.4.1',
      auth: ready ? { ok: true, method: 'oauth_token', detail: 'Long-lived OAuth token (claude setup-token), Max plan' } : { ok: false, method: null, detail: 'Not connected' },
      default_model: 'claude-opus-5-5', permission_mode: 'bypass',
    },
    projects: [],
    sessions: [],
    events: {}, // id -> [Event]
    queues: {}, // id -> [text]
    timers: {}, // id -> [timeout]
    tasks: { projects: [], tasks: [] },
    crons: [], cronRuns: [], external: [],
    telegram: {
      token: null, bot: null, chat: null, topics_enabled: false, threads: [],
      settings: { notify_crons: true, login_alerts: true, reply_mode: 'final' }, last_error: null, link: null,
    },
    backup: { configured: false, repo: null, private: null, schedule: '40 4 * * *', include: ['tasks.json', 'extensions/**', '.claude/skills/**'], always: ['**/CLAUDE.md', '**/memory.md'], history: [] },
    secrets: [],
    services: SERVICES.map(([name, label], i) => ({ name, label, active: true, enabled: true, since: t - 12 * DAY - i * 40, state: 'running' })),
    layout: { order: ['activity', 'tasks-today', 'crons', 'server', 'shop-sales', 'uptime', 'backup', 'telegram', 'claude-usage'], hidden: ['claude-usage'] },
    widgetUpdated: {},
    uptimeFixed: false,
    extensions: [
      { id: 'shop-sales', name: 'Shop sales', type: 'widget', icon: 'shopping-cart', version: '1.2.0', enabled: true, error: null, has_api: true },
      { id: 'notes', name: 'Notes', type: 'page', icon: 'notebook-pen', version: '0.3.0', enabled: true, error: null, has_api: true },
      { id: 'broken-widget', name: 'Broken widget', type: 'widget', icon: 'triangle-alert', version: '0.1.0', enabled: false, error: 'SyntaxError in api.py line 12', has_api: true },
    ],
    fs: new Map(),
  }

  if (scenario !== 'setup' && scenario !== 'onboarding') {
    // full workspace
    st.projects = WORKSPACE.map((p) => ({ name: p.name, description: p.description, topics: p.topics.map(([name, description]) => ({ name, description })) }))
  }
  if (ready) {
    seedSessions(st, t)
    if (scenario === 'maxxing') {
      seedMaxxing(st, t)
      st.settings.maxxing_mode = true
    }
    seedTasks(st, t)
    seedCrons(st, t)
    // telegram
    st.telegram.token = '7412369850:AAH3kx9-Qw2Er4Ty6Ui8Op0As1Df3Gh5Jk7'
    st.telegram.bot = { id: 7412369850, username: 'acme_maxxing_bot', name: 'Acme Maxxing' }
    st.telegram.chat = { id: 123456789, title: 'Alex', type: 'private' }
    st.telegram.topics_enabled = true
    st.telegram.threads = makeThreads(st)
    // backup
    Object.assign(st.backup, { configured: true, repo: 'alex-dev/maxxing-memory', private: true })
    const r = rng(42)
    for (let i = 7; i >= 0; i--) {
      const failed = i === 3
      st.backup.history.push({ at: t - i * DAY - 5 * HOUR + Math.floor(r() * 300), ok: !failed, commit: failed ? null : sha().slice(0, 7),
        files: failed ? 0 : 38 + Math.floor(r() * 6), error: failed ? 'remote: Repository not found. fatal: unable to access (HTTP 404) — token expired?' : null })
    }
    st.secrets = SECRET_SEED.map(([name, note, expose, value], i) => ({ name, note, expose, value, updated: t - (i * 9 + 2) * DAY }))
  } else if (scenario === 'onboarding' || scenario === 'setup') {
    st.layout.hidden = ['claude-usage']
  }
  seedFiles(st, t)
  return st
}

function makeThreads(st) {
  const th = [{ path: '', thread_id: 1, name: 'General' }, { path: '__crons__', thread_id: 2, name: 'Crons' }]
  let id = 101
  for (const p of st.projects) for (const tp of p.topics) th.push({ path: topicPath(p.name, tp.name), thread_id: id++, name: `${p.name.toUpperCase().slice(0, 2)}-${tp.name}` })
  return th
}

/* ------------------------------------------------------------------ sessions seed */
const SESSION_SEED = [
  { p: 'acme', t: 'blog', title: 'Draft: 5 ways to speed up checkout', ago: 2 * MIN, turns: 3, cost: 0.84, model: '', real: 'claude-opus-5-5', src: 'web', state: 'running', unread: false,
    last: 'I read the outline and the style guide. Now checking the existing articles so the new one links to them…' },
  { p: 'acme', t: 'blog', title: 'Editorial calendar for November', ago: 25 * MIN, turns: 4, cost: 1.12, model: 'claude-sonnet-5-5', real: 'claude-sonnet-5-5', src: 'web', unread: true,
    last: 'Here is the November calendar: 8 articles, two per week, alternating tutorials and case studies. I saved it to `calendar/2026-11.md`.' },
  { p: 'acme', t: 'blog', title: 'Daily article — Oct 11', ago: 4 * HOUR, turns: 1, cost: 0.47, model: 'claude-sonnet-5-5', real: 'claude-sonnet-5-5', src: 'cron', unread: false,
    last: 'Published “How to write a great product changelog” (1,240 words) and updated the internal links of 3 older posts.' },
  { p: 'acme', t: 'website', title: 'Fix hero image on mobile', ago: 62 * MIN, turns: 2, cost: 0.31, model: '', real: 'claude-opus-5-5', src: 'web', unread: true,
    last: 'Fixed: the hero now uses `object-cover` with an explicit aspect ratio, so it no longer overflows below 400 px. Build passes.' },
  { p: 'acme', t: 'website', title: 'Add pricing page', ago: 26 * HOUR, turns: 6, cost: 2.37, model: '', real: 'claude-opus-5-5', src: 'web', unread: false,
    last: 'The pricing page is live on the preview URL with three tiers and an FAQ. The toggle monthly / yearly is keyboard accessible.' },
  { p: 'acme', t: 'seo', title: 'Keyword research: project management tools', ago: 3 * HOUR, turns: 3, cost: 0.92, model: 'claude-opus-5-5', real: 'claude-opus-5-5', src: 'web', unread: false,
    last: 'I grouped 64 keywords into 9 clusters. The best opportunity is “kanban for small teams” (low difficulty, steady volume).' },
  { p: 'acme', t: 'seo', title: 'Weekly SEO report', ago: 2 * DAY, turns: 1, cost: 0.36, model: 'claude-sonnet-5-5', real: 'claude-sonnet-5-5', src: 'cron', unread: false, archived: true,
    last: 'Clicks +12 % week over week. Two pages lost rankings after the redesign; details in `reports/2026-W40.md`.' },
  { p: 'personal', t: 'notes', title: 'Summarise “Deep Work” highlights', ago: 5 * HOUR, turns: 2, cost: 0.22, model: 'claude-haiku-4-5-20251001', real: 'claude-haiku-4-5-20251001', src: 'telegram', unread: true,
    last: 'Summary saved to `reading/deep-work.md`: 4 rules, 12 highlights, and 3 ideas you could try this week.' },
  { p: 'personal', t: 'finance', title: 'Categorise September expenses', ago: 28 * HOUR, turns: 2, cost: 0.41, model: '', real: 'claude-opus-5-5', src: 'web', unread: false, state: 'error',
    error: 'Claude exited with code 1: API rate limit reached, retry later', last: 'I categorised 112 of 143 transactions so far.' },
  { p: 'ops', t: 'server', title: 'Caddy: add security headers', ago: 30 * MIN, turns: 3, cost: 0.58, model: '', real: 'claude-opus-5-5', src: 'web', unread: false,
    last: 'Added HSTS, `X-Content-Type-Options` and a strict `Referrer-Policy` to the Caddyfile, validated the config and reloaded Caddy.' },
  { p: 'ops', t: 'server', title: 'Investigate high disk usage', ago: 6 * HOUR, turns: 4, cost: 0.77, model: '', real: 'claude-opus-5-5', src: 'telegram', unread: false,
    last: 'Disk is at 82 %. The biggest offenders are old journal logs (6.1 GB) and Docker build cache (4.3 GB). Want me to prune both?' },
  { p: 'ops', t: 'server', title: 'Upgrade Node to 22 LTS', ago: 3 * DAY, turns: 5, cost: 1.04, model: '', real: 'claude-sonnet-5-5', src: 'web', unread: false, archived: true,
    last: 'Node 22.11.0 is installed via the official repository; all three services restarted cleanly.' },
]

function seedSessions(st, t) {
  for (const d of SESSION_SEED) {
    const id = uuid()
    const s = {
      id, title: d.title, path: topicPath(d.p, d.t), state: d.state || 'idle', queue: 0,
      created: t - d.ago - d.turns * 7 * MIN - 3 * HOUR, updated: t - d.ago, turns: d.turns, cost_usd: d.cost,
      model: d.model, real_model: d.real, context_tokens: 18000 + Math.round(d.cost * 41000), context_window: 1000000,
      archived: !!d.archived, notify: d.src !== 'web', source: d.src, unread: !!d.unread,
      last_text: d.last.slice(0, 200), error: d.error || null,
    }
    st.sessions.push(s)
    st.events[id] = conversation(s, d)
  }
}

/* Maxxing scenario: 30 sessions spread over the topics, most of them running; each finishes after 5 to 40 s
 * (startMaxxing), one of them on an error, a few with a plan waiting. A prompt sent starts a turn of 8 to 35 s. */
const MAXXING_TASKS = ['Refactor the checkout flow', 'Write the FAQ page', 'Audit the sitemap', 'Translate the landing page', 'Fix flaky login test',
  'Draft the newsletter', 'Compare hosting offers', 'Clean the CSV export', 'Add dark mode to the docs', 'Optimise hero images', 'Write release notes',
  'Map the internal links', 'Review the privacy policy', 'Profile the slow API route', 'Plan the Q1 content', 'Migrate the cron jobs', 'Design the pricing table',
  'Summarise user feedback', 'Set up uptime alerts', 'Rewrite the onboarding emails', 'Check broken links', 'Tag the photo library', 'Benchmark the search',
  'Prepare the board slides', 'Draft a job post', 'Split the big component', 'Write the API docs', 'Tidy the backlog', 'Archive old invoices', 'Estimate the redesign']
function seedMaxxing(st, t) {
  const topics = st.projects.flatMap((p) => p.topics.map((tp) => topicPath(p.name, tp.name)))
  MAXXING_TASKS.forEach((title, i) => {
    const id = uuid()
    const s = {
      id, title, path: topics[i % topics.length], state: 'running', queue: 0,
      created: t - (i + 2) * 7 * MIN, updated: t - i * 5, turns: 1 + (i % 4), cost_usd: +(0.1 + (i % 7) * 0.13).toFixed(2),
      model: '', real_model: i % 3 ? 'claude-opus-5-5' : 'claude-sonnet-5-5', context_tokens: 22000 + i * 1700, context_window: 1000000,
      archived: false, notify: false, source: 'web', unread: false, last_text: `Working on: ${title.toLowerCase()}…`, error: null,
      plan_mode: i % 9 === 4, plan_ready: false, maxxing: true,
    }
    st.sessions.push(s)
    st.events[id] = [
      { type: 'user', text: `${title}. Keep it short and tell me when it is done.`, attachments: [], at: s.created, source: 'web' },
      { type: 'init', model: s.real_model, cwd: `${ROOT}/${s.path}`, at: s.created + 2 },
      { type: 'thinking', text: `Starting: ${title}. First I read the topic memory, then the files involved.`, at: s.created + 4 },
    ]
  })
}
function maxxingFinish(s, i) {
  const model = s.real_model || 'claude-opus-5-5'
  const failed = i === 7 && s.turns < 3
  const cost = +(0.03 + Math.random() * 0.2).toFixed(4)
  s.turns += 1; s.cost_usd = +(s.cost_usd + cost).toFixed(4); s.updated = now(); s.unread = true; s.state = failed ? 'error' : 'idle'
  if (failed) {
    s.error = 'Claude exited with code 1: overloaded, retry later'
    addEvents(s, { type: 'result', ok: false, error: s.error, cost_usd: cost, duration_ms: 20000, model, at: now() })
  } else {
    const answer = s.plan_mode
      ? `**Plan for “${s.title}”**\n\n1. Read the files involved.\n2. Make the change in small steps.\n3. Check the result and report.\n\nValidate the plan and I start.`
      : `Done: **${s.title}**. I changed 3 files and checked the result. What next?`
    if (s.plan_mode) s.plan_ready = true
    s.last_text = answer.replace(/[*`#\n]/g, ' ').slice(0, 200)
    addEvents(s, { type: 'assistant', text: answer, at: now() },
      { type: 'result', ok: true, cost_usd: cost, duration_ms: 20000, model, usage: { input: 900, output: 210, cache_read: 21000, cache_write: 400 }, at: now() })
  }
  bus('sessions', 'workspace')
}
function startMaxxing() {
  if (S.scenario !== 'maxxing') return
  S.sessions.filter((s) => s.maxxing).forEach((s, i) => later(s, 5000 + Math.random() * 35000, () => maxxingFinish(s, i)))
}

function conversation(s, d) {
  const cwd = `${ROOT}/${s.path}`
  const t0 = s.created
  const model = s.real_model || 'claude-opus-5-5'
  const ev = []
  let k = 0
  const at = () => t0 + (k += 4)
  const tid = () => `toolu_${crypto.randomBytes(6).toString('hex')}`
  const isOps = s.path.startsWith('projects/ops')
  const isSite = s.path.includes('/website')

  // turn 1
  ev.push({ type: 'user', text: firstPrompt(s), attachments: s.path.endsWith('/website') ? [`${cwd}/attachments/2026-10/hero-mobile.png`] : [], at: at(), source: s.source })
  ev.push({ type: 'init', model, cwd, at: at() })
  ev.push({ type: 'thinking', text: 'The user wants me to work in this topic. I should first read the topic memory to understand the conventions, then look at the existing files before changing anything.', at: at() })
  const r1 = tid()
  ev.push({ type: 'tool_use', id: r1, name: 'Read', input: { file_path: `${cwd}/memory.md` }, summary: `Read ${s.path}/memory.md`, at: at() })
  ev.push({ type: 'tool_result', tool_use_id: r1, text: `# ${s.path.split('/').pop()} — memory\n\n## Conventions\n- Write in plain English, short paragraphs.\n- Keep a changelog of decisions below.\n\n## Decisions\n- 2026-09-30: use the shared style guide in ../../CLAUDE.md`, is_error: false, at: at() })
  const b1 = tid()
  const cmd = isOps ? 'df -h / && du -sh /var/log/journal /var/lib/docker 2>/dev/null' : isSite ? 'npm run build 2>&1 | tail -5' : 'ls -la'
  const out = isOps
    ? 'Filesystem      Size  Used Avail Use% Mounted on\n/dev/sda1        80G   66G   15G  82% /\n6.1G\t/var/log/journal\n4.3G\t/var/lib/docker'
    : isSite
      ? '> acme-website@1.4.0 build\n> astro build\n\n 12 page(s) built in 3.41s\n Complete!'
      : 'total 48\ndrwxr-xr-x 6 root root 4096 Oct 11 08:12 .\ndrwxr-xr-x 5 root root 4096 Sep 02 10:40 ..\n-rw-r--r-- 1 root root  412 Sep 02 10:40 CLAUDE.md\n-rw-r--r-- 1 root root 1893 Oct 10 18:02 memory.md\ndrwxr-xr-x 2 root root 4096 Oct 11 08:12 drafts\ndrwxr-xr-x 2 root root 4096 Oct 09 14:55 images'
  ev.push({ type: 'tool_use', id: b1, name: 'Bash', input: { command: cmd, description: 'Inspect the current state' }, summary: `Bash: ${cmd}`, at: at() })
  ev.push({ type: 'tool_result', tool_use_id: b1, text: out, is_error: false, at: at() })

  if (s.state === 'running') {
    ev.push({ type: 'assistant', text: d.last, at: at() })
    const g = tid()
    ev.push({ type: 'tool_use', id: g, name: 'Grep', input: { pattern: 'checkout', path: `${cwd}/drafts` }, summary: 'Grep "checkout" in drafts/', at: at() })
    ev.push({ type: 'tool_result', tool_use_id: g, text: 'drafts/2026-09-cart-abandonment.md:14: …a slow checkout is the first reason…\ndrafts/2026-10-payment-methods.md:3: …one-page checkout…', is_error: false, at: at() })
    const w = tid()
    ev.push({ type: 'tool_use', id: w, name: 'Write', input: { file_path: `${cwd}/drafts/2026-10-speed-up-checkout.md`, content: '# 5 ways to speed up checkout\n…' }, summary: 'Write drafts/2026-10-speed-up-checkout.md', at: at() })
    return ev
  }

  ev.push({ type: 'assistant', text: answerMarkdown(s, d), at: at() })
  ev.push({ type: 'result', ok: true, cost_usd: +(s.cost_usd / Math.max(1, s.turns) * 1.3).toFixed(4), duration_ms: 41250, model,
    usage: { input: 1840, output: 1265, cache_read: 21430, cache_write: 4120 }, at: at() })

  if (s.turns > 1) {
    ev.push({ type: 'user', text: 'Great, thanks. Can you also update the topic memory with what we decided?', attachments: [], at: at(), source: s.source })
    ev.push({ type: 'init', model, cwd, at: at() })
    const e1 = tid()
    ev.push({ type: 'tool_use', id: e1, name: 'Edit', input: { file_path: `${cwd}/memory.md`, old_string: '## Decisions', new_string: `## Decisions\n- 2026-10-11: ${s.title}` }, summary: `Edit ${s.path}/memory.md`, at: at() })
    ev.push({ type: 'tool_result', tool_use_id: e1, text: 'The file has been updated successfully.', is_error: false, at: at() })
    if (s.state === 'error') {
      ev.push({ type: 'note', text: 'Turn failed: ' + s.error, level: 'error', at: at() })
      return ev
    }
    ev.push({ type: 'assistant', text: `Done — I added a line under **Decisions** in \`memory.md\`.\n\n${d.last}`, at: at() })
    ev.push({ type: 'result', ok: true, cost_usd: +(s.cost_usd / s.turns * 0.7).toFixed(4), duration_ms: 12890, model,
      usage: { input: 640, output: 212, cache_read: 25110, cache_write: 380 }, at: at() })
  }
  if (s.archived) ev.push({ type: 'note', text: 'Session archived.', level: 'info', at: at() })
  return ev
}

function firstPrompt(s) {
  if (s.source === 'cron') return `[cron] ${s.title}. Follow the editorial plan and the memory of this topic, then report what you did in 3 lines.`
  return `${s.title}. Please look at what we already have in this topic first, then propose and apply the changes.`
}

function answerMarkdown(s, d) {
  const isOps = s.path.startsWith('projects/ops')
  const code = isOps
    ? '```caddyfile\nui.example.com {\n\theader {\n\t\tStrict-Transport-Security "max-age=31536000; includeSubDomains"\n\t\tX-Content-Type-Options nosniff\n\t\tReferrer-Policy strict-origin-when-cross-origin\n\t}\n\treverse_proxy 127.0.0.1:8787\n}\n```'
    : s.path.includes('/website')
      ? '```astro\n<img\n  src={hero}\n  alt="Acme dashboard"\n  class="w-full aspect-[4/3] object-cover sm:aspect-[16/9]"\n  loading="eager"\n/>\n```'
      : '```markdown\n## Outline\n1. Why speed matters (data)\n2. Remove optional fields\n3. Offer express wallets\n4. Show progress clearly\n5. Measure and iterate\n```'
  return [
    `## Summary`, '', d.last, '',
    `### What I changed`, '',
    `- Read the topic memory and the existing files`,
    `- Applied the change and checked the result`,
    `- Kept the conventions from \`CLAUDE.md\``, '',
    code, '',
    `| Item | Before | After |`, `|---|---|---|`, `| Files touched | 0 | 2 |`, `| Checks | — | passing |`, '',
    `> Tip: ask me to **commit** when you are happy with it.`,
  ].join('\n')
}

/* ------------------------------------------------------------------ tasks seed */
function seedTasks(st, t) {
  const today = new Date().toISOString().slice(0, 10)
  const day = (n) => new Date(Date.now() + n * DAY * 1000).toISOString().slice(0, 10)
  st.tasks.projects = [
    { id: 'tp_acme', name: 'Acme', color: '#6366f1' },
    { id: 'tp_personal', name: 'Personal', color: '#10b981' },
    { id: 'tp_ops', name: 'Ops', color: '#f59e0b' },
  ]
  const T = (title, status, priority, due, project_id, topic_path, labels, notes = '', ageDays = 3) => ({
    id: rid('t'), title, notes, status, priority, due, project_id, topic_path, labels,
    created: t - ageDays * DAY, updated: t - Math.min(ageDays, 1) * DAY / 2, done_at: status === 'done' ? t - DAY / 3 : null, order: 0,
  })
  st.tasks.tasks = [
    T('Review the checkout article draft', 'doing', 2, today, 'tp_acme', topicPath('acme', 'blog'), ['writing'], 'Check the numbers in section 2.'),
    T('Renew the ui.example.com certificate alert', 'todo', 1, today, 'tp_ops', topicPath('ops', 'server'), ['infra']),
    T('Call the accountant about Q3', 'todo', 3, today, 'tp_personal', topicPath('personal', 'finance'), ['admin'], 'Bring the categorised expenses export.'),
    T('Publish pricing page', 'todo', 2, day(2), 'tp_acme', topicPath('acme', 'website'), ['launch']),
    T('Prune Docker build cache', 'todo', 1, day(1), 'tp_ops', topicPath('ops', 'server'), ['infra', 'disk']),
    T('Fix 404s found by the SEO audit', 'doing', 2, day(3), 'tp_acme', topicPath('acme', 'seo'), ['seo'], '', 6),
    T('Read “Shape Up” chapters 4–6', 'todo', 0, null, 'tp_personal', topicPath('personal', 'notes'), ['reading'], '', 10),
    T('Set up a monthly budget review cron', 'todo', 1, day(7), 'tp_personal', null, ['idea'], '', 12),
    T('Migrate blog images to WebP', 'done', 1, day(-2), 'tp_acme', topicPath('acme', 'blog'), ['performance'], '', 9),
    T('Rotate the Cloudflare API token', 'done', 2, day(-4), 'tp_ops', null, ['security'], '', 14),
    T('Write the November newsletter', 'todo', 1, day(-1), 'tp_acme', null, ['writing'], 'Overdue — reuse the calendar.', 5),
  ]
  st.tasks.tasks.forEach((x, i) => { x.order = (i + 1) * 1000 })
}

/* ------------------------------------------------------------------ crons */
const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const LIM = [[0, 59], [0, 23], [1, 31], [1, 12], [0, 7]]

function cronValid(expr) {
  const f = String(expr || '').trim().split(/\s+/)
  if (f.length !== 5) return false
  return f.every((x, i) => x.split(',').every((part) => {
    const m = part.match(/^(\*|(\d+)(?:-(\d+))?)(?:\/(\d+))?$/)
    if (!m) return false
    const a = m[2] !== undefined ? +m[2] : null, b = m[3] !== undefined ? +m[3] : null
    if (a !== null && (a < LIM[i][0] || a > LIM[i][1])) return false
    if (b !== null && (b < LIM[i][0] || b > LIM[i][1] || b < a)) return false
    if (m[4] !== undefined && +m[4] < 1) return false
    return true
  }))
}
function fieldMatch(field, v, i) {
  return field.split(',').some((part) => {
    const m = part.match(/^(\*|(\d+)(?:-(\d+))?)(?:\/(\d+))?$/)
    let lo = LIM[i][0], hi = LIM[i][1]
    if (m[1] !== '*') { lo = +m[2]; hi = m[3] !== undefined ? +m[3] : (m[4] ? LIM[i][1] : lo) }
    const step = m[4] ? +m[4] : 1
    const val = i === 4 && v === 0 && hi === 7 && lo > 0 ? 7 : v
    return val >= lo && val <= hi && (val - lo) % step === 0
  })
}
function cronNext(expr, n = 5, from = Date.now()) {
  if (!cronValid(expr)) return []
  const f = expr.trim().split(/\s+/)
  const out = []
  let d = new Date(Math.floor(from / 60000) * 60000 + 60000)
  for (let i = 0; i < 366 * 24 * 60 && out.length < n; i++, d = new Date(d.getTime() + 60000)) {
    const dowF = f[4], domF = f[2]
    const domOk = fieldMatch(domF, d.getUTCDate(), 2), dowOk = fieldMatch(dowF, d.getUTCDay(), 4)
    const dayOk = domF !== '*' && dowF !== '*' ? domOk || dowOk : domOk && dowOk
    if (fieldMatch(f[0], d.getUTCMinutes(), 0) && fieldMatch(f[1], d.getUTCHours(), 1) && fieldMatch(f[3], d.getUTCMonth() + 1, 3) && dayOk) out.push(d.getTime() / 1000)
  }
  return out
}
function cronHuman(expr) {
  if (expr === '@reboot') return 'At boot'
  if (!cronValid(expr)) return 'Invalid expression'
  const [mi, h, dom, mon, dow] = expr.trim().split(/\s+/)
  const pad = (x) => String(x).padStart(2, '0')
  const num = (v) => /^\d+$/.test(v)
  const rest = dom === '*' && mon === '*' && dow === '*'
  if (mi === '*' && h === '*' && rest) return 'Every minute'
  if (/^\*\/\d+$/.test(mi) && h === '*' && rest) return `Every ${mi.slice(2)} minutes`
  if (num(mi) && h === '*' && rest) return `Every hour at :${pad(mi)}`
  if (num(mi) && /^\*\/\d+$/.test(h) && rest) return `Every ${h.slice(2)} hours at :${pad(mi)}`
  if (num(mi) && num(h)) {
    const at = `${pad(h)}:${pad(mi)}`
    if (rest) return `Every day at ${at}`
    if (dom === '*' && mon === '*' && num(dow)) return `Every ${DOW[+dow % 7]} at ${at}`
    if (dom === '*' && mon === '*' && dow === '1-5') return `Weekdays at ${at}`
    if (num(dom) && mon === '*' && dow === '*') return `On day ${dom} of every month at ${at}`
  }
  return `Custom schedule (${expr})`
}
const cronOut = (c) => ({ ...c, next_run: c.enabled ? cronNext(c.schedule, 1)[0] ?? null : null, human: cronHuman(c.schedule), running: c.id === 'c_blog' })

function seedCrons(st, t) {
  const base = { command: '', topic_path: '', prompt: '', model: '', reuse_session: false, enabled: true, notify: 'failure', timeout_s: 600 }
  st.crons = [
    { ...base, id: 'c_backup', name: 'Memory backup', schedule: '40 4 * * *', kind: 'shell', command: 'maxxing backup run', last_run: { at: t - 5 * HOUR, ok: true, code: 0, duration_s: 6.2 } },
    { ...base, id: 'c_blog', name: 'Daily blog article', schedule: '0 7 * * *', kind: 'claude', topic_path: topicPath('acme', 'blog'),
      prompt: 'Write the next article from the editorial plan, publish it, and update internal links.', model: 'claude-sonnet-5-5', notify: 'always', timeout_s: 1800,
      last_run: { at: t - 4 * HOUR, ok: true, code: 0, duration_s: 412.8 } },
    { ...base, id: 'c_seo', name: 'Weekly SEO report', schedule: '30 8 * * 1', kind: 'claude', topic_path: topicPath('acme', 'seo'),
      prompt: 'Produce the weekly SEO report from Search Console data and save it under reports/.', model: 'claude-sonnet-5-5', reuse_session: true,
      last_run: { at: t - 2 * DAY, ok: true, code: 0, duration_s: 233.1 } },
    { ...base, id: 'c_uptime', name: 'Uptime check', schedule: '*/15 * * * *', kind: 'shell', command: 'curl -fsS --max-time 10 https://www.example.com/healthz', timeout_s: 30,
      last_run: { at: t - 9 * MIN, ok: false, code: 22, duration_s: 10.0 } },
    { ...base, id: 'c_cleanup', name: 'Clean old attachments', schedule: '0 3 1 * *', kind: 'shell', command: 'find /root/maxxing -path "*/attachments/*" -mtime +90 -delete', enabled: false, notify: 'never',
      last_run: { at: t - 40 * DAY, ok: true, code: 0, duration_s: 1.4 } },
  ]
  st.external = [
    { schedule: '0 0 * * 0', command: '/usr/sbin/logrotate /etc/logrotate.conf', human: cronHuman('0 0 * * 0') },
    { schedule: '@reboot', command: '/usr/local/bin/mount-backups.sh', human: 'At boot' },
  ]
  const r = rng(7)
  const blogIds = st.sessions.filter((s) => s.source === 'cron').map((s) => s.id)
  for (let i = 0; i < 36; i++) {
    const c = st.crons[Math.floor(r() * 4)]
    const ok = c.id === 'c_uptime' ? r() > 0.25 : r() > 0.06
    const at = t - i * 3.3 * HOUR - Math.floor(r() * 900)
    st.cronRuns.push({ id: rid('r'), cron_id: c.id, name: c.name, at, ok, code: ok ? 0 : (c.id === 'c_uptime' ? 22 : 1),
      duration_s: +(c.kind === 'claude' ? 120 + r() * 400 : r() * 10).toFixed(1),
      output_tail: ok ? (c.kind === 'claude' ? 'Turn finished: article published, 3 links updated.' : 'OK') : (c.id === 'c_uptime' ? 'curl: (22) The requested URL returned error: 503' : 'Error: process exited with code 1'),
      session_id: c.kind === 'claude' && c.id === 'c_blog' && blogIds.length ? blogIds[0] : null })
  }
  st.cronRuns.sort((a, b) => b.at - a.at)
}

/* ------------------------------------------------------------------ files */
function fsAdd(st, rel, content, mtime, mime) {
  const abs = rel.startsWith('/') ? rel : `${ROOT}/${rel}`
  fsMkdirp(st, path.dirname(abs), mtime)
  const m = mime || mimeOf(abs)
  const body = content ?? ''
  st.fs.set(abs, { type: 'file', content: body, mtime, mime: m, size: typeof body === 'string' ? Buffer.byteLength(body) : body.length })
}
function fsMkdirp(st, abs, mtime = now()) {
  let cur = abs
  const chain = []
  while (cur.startsWith(ROOT) && !st.fs.has(cur)) { chain.push(cur); if (cur === ROOT) break; cur = path.dirname(cur) }
  for (const d of chain) st.fs.set(d, { type: 'dir', mtime, mime: 'inode/directory', size: 4096 })
}

function seedFiles(st, t) {
  st.fs.set(ROOT, { type: 'dir', mtime: t - 40 * DAY, mime: 'inode/directory', size: 4096 })
  fsAdd(st, 'CLAUDE.md', '# Workspace\n\n@memory.md\n\nYou are working in the Harness Maxxing workspace. Projects live in `projects/<name>/`, topics in `projects/<name>/topics/<topic>/`.\n\n## Rules\n- Write durable facts in the closest `memory.md`.\n- Never print secrets.\n', t - 30 * DAY)
  fsAdd(st, 'memory.md', '# Global memory\n\n## Preferences\n- Answers in English, concise.\n- Timezone Europe/Paris.\n\n## Facts\n- Server: Ubuntu 24.04, 4 vCPU, 8 GB RAM.\n- Public URL: https://ui.example.com\n', t - 2 * DAY)
  fsAdd(st, 'tasks.json', JSON.stringify(st.tasks, null, 2), t - HOUR)
  for (const p of st.projects) {
    fsAdd(st, `${projPath(p.name)}/CLAUDE.md`, `# Project ${p.name}\n\n> ${p.description}\n\n@memory.md\n`, t - 20 * DAY)
    fsAdd(st, `${projPath(p.name)}/memory.md`, `# ${p.name} — memory\n\n- Created for: ${p.description}\n`, t - 3 * DAY)
    for (const tp of p.topics) {
      const base = topicPath(p.name, tp.name)
      fsAdd(st, `${base}/CLAUDE.md`, `# Topic ${p.name}/${tp.name}\n\n> ${tp.description}\n\n@memory.md\n`, t - 20 * DAY)
      fsAdd(st, `${base}/memory.md`, `# ${tp.name} — memory\n\n## Conventions\n- Write in plain English, short paragraphs.\n\n## Decisions\n- 2026-09-30: use the shared style guide\n`, t - DAY)
    }
  }
  if (st.projects.length) {
    const blog = topicPath('acme', 'blog')
    fsAdd(st, `${blog}/drafts/2026-10-speed-up-checkout.md`, '# 5 ways to speed up checkout\n\nA slow checkout costs sales. Here are five changes that make a measurable difference.\n\n## 1. Remove optional fields\n\nEvery field is friction…\n', t - 3 * MIN)
    fsAdd(st, `${blog}/drafts/2026-09-cart-abandonment.md`, '# Why carts get abandoned\n\nA slow checkout is the first reason…\n', t - 20 * DAY)
    fsAdd(st, `${blog}/calendar/2026-11.md`, '# November 2026\n\n| Week | Tuesday | Friday |\n|---|---|---|\n| 45 | Changelog tips | Case study: Globex |\n| 46 | Kanban basics | Pricing pages |\n', t - 25 * MIN)
    fsAdd(st, `${blog}/images/cover-checkout.png`, PLACEHOLDER_SVG('cover-checkout.png'), t - 2 * HOUR, 'image/png')
    fsAdd(st, `${blog}/images/hero.jpg`, PLACEHOLDER_SVG('hero.jpg'), t - 5 * DAY, 'image/jpeg')
    const site = topicPath('acme', 'website')
    fsAdd(st, `${site}/src/pages/index.astro`, '---\nimport Layout from "../layouts/Layout.astro"\nimport hero from "../assets/hero.webp"\n---\n<Layout title="Acme — Ship faster">\n  <h1>Ship faster</h1>\n</Layout>\n', t - 62 * MIN)
    fsAdd(st, `${site}/src/styles/global.css`, ':root { --brand: #6366f1; }\nbody { font-family: Inter, sans-serif; }\n', t - 9 * DAY)
    fsAdd(st, `${site}/package.json`, '{\n  "name": "acme-website",\n  "version": "1.4.0",\n  "scripts": { "build": "astro build" }\n}\n', t - 9 * DAY)
    fsAdd(st, `${site}/attachments/2026-10/hero-mobile.png`, PLACEHOLDER_SVG('hero-mobile.png'), t - 70 * MIN, 'image/png')
    fsAdd(st, `${topicPath('acme', 'seo')}/keywords.csv`, 'keyword,volume,difficulty,cluster\nkanban for small teams,2400,18,kanban\nproject management tool,40500,72,generic\ntask board free,5400,31,kanban\n', t - 3 * HOUR)
    fsAdd(st, `${topicPath('acme', 'seo')}/reports/2026-W40.md`, '# SEO report — week 40\n\n- Clicks: 3,412 (+12 %)\n- Impressions: 88,903 (+4 %)\n', t - 2 * DAY)
    fsAdd(st, `${topicPath('personal', 'notes')}/ideas.md`, '# Ideas\n\n- A weekly digest of my sessions\n- Track reading time\n', t - 6 * DAY)
    fsAdd(st, `${topicPath('personal', 'notes')}/reading/deep-work.md`, '# Deep Work — highlights\n\n1. Work deeply\n2. Embrace boredom\n3. Quit social media\n4. Drain the shallows\n', t - 5 * HOUR)
    fsAdd(st, `${topicPath('personal', 'finance')}/budget-2026.csv`, 'month,income,expenses\n2026-07,5200,3890\n2026-08,5200,4120\n2026-09,5350,3975\n', t - 28 * HOUR)
    fsAdd(st, `${topicPath('ops', 'server')}/deploy.sh`, '#!/usr/bin/env bash\nset -euo pipefail\ncd /srv/acme-website\ngit pull --ff-only\nnpm ci && npm run build\nsystemctl reload caddy\n', t - 8 * DAY)
    fsAdd(st, `${topicPath('ops', 'server')}/caddy/Caddyfile`, 'ui.example.com {\n\treverse_proxy 127.0.0.1:8787\n}\n', t - 30 * MIN)
    fsAdd(st, `${topicPath('ops', 'server')}/demo.mp4`, Buffer.alloc(2048), t - 12 * DAY, 'video/mp4')
  }
  fsAdd(st, 'extensions/shop-sales/manifest.json', JSON.stringify({ id: 'shop-sales', name: 'Shop sales', type: 'widget', icon: 'shopping-cart', version: '1.2.0', span: 1, ttl: 1800 }, null, 2), t - 15 * DAY)
  fsAdd(st, 'extensions/shop-sales/api.py', 'def card(ctx):\n    orders = ctx.http.get("https://api.example-shop.com/orders?days=7").json()\n    return {"blocks": [{"type": "stat", "label": "Today", "value": len(orders)}]}\n', t - 15 * DAY)
  fsAdd(st, 'extensions/notes/manifest.json', JSON.stringify({ id: 'notes', name: 'Notes', type: 'page', icon: 'notebook-pen', version: '0.3.0' }, null, 2), t - 10 * DAY)
  fsAdd(st, 'extensions/notes/api.py', 'import time\n\ndef handle(ctx, method, path, query, body):\n    if path == "hello":\n        return {"hello": "world", "at": time.time()}\n    return {"error": "not_found"}\n', t - 10 * DAY)
  fsAdd(st, 'extensions/notes/page.js', NOTES_PAGE_JS, t - 10 * DAY)
  fsAdd(st, 'extensions/broken-widget/manifest.json', JSON.stringify({ id: 'broken-widget', name: 'Broken widget', type: 'widget', icon: 'triangle-alert', version: '0.1.0' }, null, 2), t - 4 * DAY)
  fsAdd(st, 'extensions/broken-widget/api.py', 'def card(ctx)\n    return {"blocks": []}\n', t - 4 * DAY)
}

function PLACEHOLDER_SVG(label = 'image', w = 640, h = 400) {
  const hue = [...label].reduce((a, c) => a + c.charCodeAt(0), 0) % 360
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">` +
    `<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue},55%,55%)"/><stop offset="1" stop-color="hsl(${(hue + 60) % 360},55%,35%)"/></linearGradient></defs>` +
    `<rect width="100%" height="100%" fill="url(#g)"/>` +
    `<text x="50%" y="50%" fill="#fff" font-family="sans-serif" font-size="${Math.round(w / 18)}" text-anchor="middle" dominant-baseline="middle">${label.replace(/[<&>]/g, '')}</text></svg>`
}

const NOTES_PAGE_JS = `// Example page extension (mock). ctx = { api(path, opts), navigate, theme, t }
export function mount(el, ctx) {
  el.innerHTML = ''
  const wrap = document.createElement('div')
  wrap.style.cssText = 'padding:24px;max-width:640px'
  const h = document.createElement('h2')
  h.textContent = 'Notes'
  h.style.cssText = 'font-size:20px;font-weight:600;margin:0 0 6px'
  const p = document.createElement('p')
  p.textContent = 'Example page extension. Current theme: ' + (ctx && ctx.theme)
  p.style.cssText = 'opacity:.7;margin:0'
  const btn = document.createElement('button')
  btn.textContent = 'Call api("hello")'
  btn.style.cssText = 'margin-top:16px;padding:8px 14px;border:1px solid currentColor;border-radius:8px;background:transparent;color:inherit;cursor:pointer;font:inherit'
  const out = document.createElement('pre')
  out.style.cssText = 'margin-top:12px;padding:12px;border-radius:8px;background:rgba(127,127,127,.12);font-size:13px;white-space:pre-wrap'
  out.textContent = '(no call yet)'
  btn.onclick = async () => {
    out.textContent = 'Loading…'
    try {
      let r = await ctx.api('hello')
      if (r && typeof r.json === 'function') r = await r.json()
      out.textContent = JSON.stringify(r, null, 2)
    } catch (e) {
      out.textContent = 'Error: ' + ((e && e.message) || e)
    }
  }
  wrap.append(h, p, btn, out)
  el.append(wrap)
  return () => { el.innerHTML = '' }
}
`

/* =================================================================== derived objects */
function topicObj(p, tp) {
  const pth = topicPath(p.name, tp.name)
  const ss = S.sessions.filter((s) => s.path === pth && !s.archived)
  const th = S.telegram.threads.find((x) => x.path === pth)
  return { name: tp.name, project: p.name, path: pth, description: tp.description || '', session_count: ss.length,
    running: ss.filter((s) => s.state === 'running').length, unread: ss.filter((s) => s.unread).length, telegram_thread: th ? th.thread_id : null }
}
function projectObj(p) {
  const pp = projPath(p.name)
  return { name: p.name, path: pp, description: p.description || '', topics: p.topics.map((tp) => topicObj(p, tp)),
    session_count: S.sessions.filter((s) => (s.path === pp || s.path.startsWith(pp + '/')) && !s.archived).length }
}
const findProject = (name) => S.projects.find((p) => p.name === name) || fail(404, 'not_found', `Project “${name}” not found`)
const findSession = (id) => S.sessions.find((s) => s.id === id) || fail(404, 'not_found', 'Session not found')

function onboardingObj() {
  return { completed: S.onboarding_completed, steps: { password: !S.setup_required && !!S.password, claude: S.claude.auth.ok,
    workspace: S.projects.length > 0, telegram: !!S.telegram.chat, backup: S.backup.configured } }
}

/* =================================================================== SSE buses */
const busClients = new Set()
const sessionSubs = new Map() // id -> Set(res)

function sseOpen(req, res) {
  res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store', Connection: 'keep-alive', 'X-Accel-Buffering': 'no' })
  res.write('retry: 3000\n\n')
}
const sseSend = (res, event, data) => { try { res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`) } catch {} }

function bus(...topics) {
  const data = { topics: [...new Set(topics)] }
  for (const c of busClients) sseSend(c, 'invalidate', data)
  // Like the server's session streams: a `state` frame whenever the Session changed (any write announces `sessions`).
  if (topics.includes('sessions')) for (const [id, subs] of sessionSubs) {
    const s = S.sessions.find((x) => x.id === id)
    if (!s) { for (const r of subs) sseSend(r, 'state', null); sessionSubs.delete(id); continue }
    const sig = JSON.stringify(s)
    for (const r of subs) if (r.mxState !== sig) { r.mxState = sig; sseSend(r, 'state', s) }
  }
}
function pushEvents(id, newEvents) {
  const subs = sessionSubs.get(id)
  if (!subs) return
  const s = S.sessions.find((x) => x.id === id)
  const next = (S.events[id] || []).length
  for (const r of subs) {
    if (newEvents.length) sseSend(r, 'events', { events: newEvents, next })
    if (s) sseSend(r, 'state', s)
  }
}
function addEvents(s, ...evs) {
  (S.events[s.id] ||= []).push(...evs)
  pushEvents(s.id, evs)
}

setInterval(() => {
  for (const c of busClients) c.write(': ping\n\n')
  for (const set of sessionSubs.values()) for (const c of set) c.write(': ping\n\n')
}, 15000).unref()
setInterval(() => bus('health'), 20000).unref()

/* =================================================================== simulated turns */
function later(s, ms, fn) {
  const g = GEN
  const h = setTimeout(() => { if (g === GEN) fn() }, ms)
  ;(S.timers[s.id] ||= []).push(h)
}
function clearTimers(s) { for (const h of S.timers[s.id] || []) clearTimeout(h); S.timers[s.id] = [] }

function startTurn(s, text, attachments = []) {
  const cwd = `${ROOT}/${s.path}`
  const model = s.model || S.claude.default_model
  s.state = 'running'; s.error = null; s.updated = now()
  if (s.plan_ready) s.plan_ready = false
  // Maxxing scenario: turns of 8 to 35 s, so several sessions finish while the user types
  const k = S.scenario === 'maxxing' ? (8000 + Math.random() * 27000) / 3400 : 1
  addEvents(s, { type: 'user', text, attachments, at: now(), source: 'web' }, { type: 'init', model, cwd, at: now() })
  bus('sessions', 'workspace')
  const tu = `toolu_${crypto.randomBytes(6).toString('hex')}`
  later(s, 700 * k, () => addEvents(s, { type: 'thinking', text: `Let me look at the files in this topic before answering: "${text.slice(0, 80)}"`, at: now() }))
  later(s, 1500 * k, () => addEvents(s, { type: 'tool_use', id: tu, name: 'Bash', input: { command: 'ls -la', description: 'List topic files' }, summary: 'Bash: ls -la', at: now() }))
  later(s, 2200 * k, () => addEvents(s, { type: 'tool_result', tool_use_id: tu, text: 'total 24\n-rw-r--r-- 1 root root  412 CLAUDE.md\n-rw-r--r-- 1 root root 1893 memory.md\ndrwxr-xr-x 2 root root 4096 drafts', is_error: false, at: now() }))
  later(s, 3400 * k, () => {
    const answer = `Sure. Here is what I found for **“${text.slice(0, 60)}”**:\n\n- The topic contains a \`CLAUDE.md\`, a \`memory.md\` and a \`drafts/\` folder.\n- Nothing needed to change yet.\n\n\`\`\`bash\nls -la ${s.path}\n\`\`\`\n\nTell me if you want me to go further.`
    const cost = +(0.02 + Math.random() * 0.12).toFixed(4)
    s.turns += 1; s.cost_usd = +(s.cost_usd + cost).toFixed(4); s.real_model = model; s.context_tokens = 20000 + Math.floor(Math.random() * 30000)
    s.last_text = answer.replace(/[*`#]/g, '').slice(0, 200); s.updated = now(); s.unread = true; s.state = 'idle'
    addEvents(s, { type: 'assistant', text: answer, at: now() },
      { type: 'result', ok: true, cost_usd: cost, duration_ms: 3400, model, usage: { input: 820, output: 164, cache_read: 19870, cache_write: 512 }, at: now() })
    bus('sessions', 'workspace')
    const q = S.queues[s.id] || []
    if (q.length) { const nxt = q.shift(); s.queue = q.length; startTurn(s, nxt.text, nxt.attachments) }
  })
}

/* =================================================================== dashboard */
function widgetDefs() {
  const ext = S.extensions.find((e) => e.id === 'shop-sales')
  const defs = [
    { id: 'activity', title: 'Activity', icon: 'activity', span: 2, source: 'builtin', card: cardActivity },
    { id: 'tasks-today', title: 'Today', icon: 'list-checks', span: 1, source: 'builtin', card: cardTasks },
    { id: 'crons', title: 'Crons', icon: 'clock', span: 1, source: 'builtin', card: cardCrons },
    { id: 'server', title: 'Server', icon: 'server', span: 1, source: 'builtin', card: cardServer },
    { id: 'backup', title: 'Backup', icon: 'database-backup', span: 1, source: 'builtin', card: cardBackup },
    { id: 'telegram', title: 'Telegram', icon: 'send', span: 1, source: 'builtin', card: cardTelegram },
    { id: 'claude-usage', title: 'Claude usage', icon: 'gauge', span: 1, source: 'builtin', card: cardUsage },
    { id: 'uptime', title: 'Website uptime', icon: 'radar', span: 2, source: 'builtin', card: cardUptime },
  ]
  if (ext && ext.enabled) defs.push({ id: 'shop-sales', title: 'Shop sales', icon: 'shopping-cart', span: 1, source: 'extension', card: cardShop })
  return defs
}
function renderWidget(d) {
  const hidden = S.layout.hidden.includes(d.id)
  const base = { id: d.id, title: d.title, icon: d.icon, span: d.span, source: d.source, hidden }
  if (hidden) return { ...base, card: null, error: null }
  if (d.id === 'uptime' && !S.uptimeFixed) return { ...base, card: null, error: 'Timeout after 10 s' }
  try {
    const card = d.card()
    card.updated = S.widgetUpdated[d.id] || now() - 120
    return { ...base, card, error: null }
  } catch (e) { return { ...base, card: null, error: String(e.message || e) } }
}
function dashboard() {
  const defs = widgetDefs()
  const idx = (id) => { const i = S.layout.order.indexOf(id); return i === -1 ? 1e6 : i }
  defs.sort((a, b) => idx(a.id) - idx(b.id))
  return { widgets: defs.map(renderWidget) }
}

const fmtDay = (ts) => new Date(ts * 1000).toISOString().slice(5, 10)
function cardActivity() {
  const r = rng(11), t = now()
  const pts = [], cost = []
  for (let i = 13; i >= 0; i--) { const v = S.sessions.length ? 3 + Math.floor(r() * 9) + (i < 3 ? 4 : 0) : 0; pts.push([fmtDay(t - i * DAY), v]); cost.push([fmtDay(t - i * DAY), +(v * (0.25 + r() * 0.2)).toFixed(2)]) }
  const week = pts.slice(-7).reduce((a, p) => a + p[1], 0)
  const prev = pts.slice(0, 7).reduce((a, p) => a + p[1], 0)
  const spend = S.sessions.reduce((a, s) => a + s.cost_usd, 0)
  return { title: 'Activity', link: '/sessions', blocks: [
    { type: 'stats', items: [
      { label: 'Turns this week', value: week, delta: prev ? `${week >= prev ? '+' : ''}${Math.round((week - prev) / prev * 100)} %` : undefined, tone: week >= prev ? 'ok' : 'warn' },
      { label: 'Sessions', value: S.sessions.filter((s) => !s.archived).length, hint: `${S.sessions.filter((s) => s.state === 'running').length} running` },
      { label: 'Spend (API equiv.)', value: `$${spend.toFixed(2)}`, hint: 'last 14 days' },
    ] },
    { type: 'chart', kind: 'line', unit: 'turns', series: [{ name: 'Turns', points: pts }, { name: 'Cost ($)', points: cost }] },
  ] }
}
function cardTasks() {
  const today = new Date().toISOString().slice(0, 10)
  const items = S.tasks.tasks.filter((x) => x.status !== 'done' && (x.status === 'doing' || (x.due && x.due <= today)))
    .sort((a, b) => b.priority - a.priority)
    .map((x) => ({ title: x.title, subtitle: x.due && x.due < today ? `Overdue · ${x.due}` : x.status === 'doing' ? 'In progress' : 'Due today',
      value: ['', 'P1', 'P2', 'P3'][x.priority] || undefined, href: '/tasks', status: x.due && x.due < today ? 'error' : x.priority >= 2 ? 'warn' : 'ok' }))
  return { title: 'Today', link: '/tasks', blocks: [{ type: 'list', items, empty: 'Nothing due today' }] }
}
function cardCrons() {
  const items = S.crons.map((c) => ({ title: c.name, subtitle: cronHuman(c.schedule) + (c.enabled ? '' : ' · disabled'),
    value: c.last_run ? (c.last_run.ok ? 'ok' : `exit ${c.last_run.code}`) : '—', href: '/crons',
    status: !c.enabled ? undefined : c.last_run && !c.last_run.ok ? 'error' : 'ok' }))
  const failing = S.crons.filter((c) => c.enabled && c.last_run && !c.last_run.ok).length
  return { title: 'Crons', link: '/crons', status: failing ? 'warn' : 'ok', blocks: [{ type: 'list', items, empty: 'No cron jobs yet' }] }
}
function cardServer() {
  const h = healthObj()
  return { title: 'Server', link: '/settings/system', status: h.issues.some((i) => i.level === 'error') ? 'error' : h.issues.length ? 'warn' : 'ok', blocks: [
    { type: 'stats', items: [{ label: 'CPU', value: `${h.cpu_pct} %` }, { label: 'Load', value: h.load[0].toFixed(2) }, { label: 'Uptime', value: `${Math.floor(h.uptime_s / DAY)} d` }] },
    { type: 'progress', label: 'Disk', value: h.disk.pct, max: 100, hint: `${(h.disk.free / 1e9).toFixed(1)} GB free` },
    { type: 'progress', label: 'Memory', value: +((h.mem.total - h.mem.avail) / 1e9).toFixed(1), max: +(h.mem.total / 1e9).toFixed(1), hint: 'GB used' },
    { type: 'table', columns: ['Service', 'State'], rows: S.services.map((s) => [s.label, s.active ? 'active' : 'inactive']) },
  ] }
}
function cardBackup() {
  const last = S.backup.history.at(-1) || null
  if (!S.backup.configured) return { title: 'Backup', link: '/settings/backup', status: 'warn', blocks: [{ type: 'stat', label: 'Status', value: 'Not configured', tone: 'warn' }, { type: 'markdown', text: 'Back up your memory files to a **private** GitHub repository. [Set it up](/settings/backup).' }] }
  const age = last ? (now() - last.at) / HOUR : null
  return { title: 'Backup', link: '/settings/backup', status: last && last.ok ? 'ok' : 'error', blocks: [
    { type: 'stat', label: 'Last backup', value: age == null ? 'never' : `${Math.round(age)} h ago`, hint: last && last.commit ? `commit ${last.commit}` : undefined, tone: last && last.ok ? 'ok' : 'error' },
    { type: 'markdown', text: `Repository **${S.backup.repo}** (private) · ${last ? last.files : 0} files · schedule \`${S.backup.schedule}\`` },
  ] }
}
function cardTelegram() {
  const tg = S.telegram
  return { title: 'Telegram', link: '/settings/telegram', status: tg.chat ? 'ok' : 'warn', blocks: [
    { type: 'stat', label: tg.bot ? `@${tg.bot.username}` : 'Bot', value: tg.chat ? 'Linked' : tg.bot ? 'Waiting for /start' : 'Not configured',
      hint: tg.chat ? `${tg.threads.length} threads` : undefined, tone: tg.chat ? 'ok' : 'warn' },
  ] }
}
function cardUsage() {
  return { title: 'Claude usage', blocks: [{ type: 'stat', label: 'Plan usage', value: 'Unavailable', hint: 'Experimental endpoint disabled', tone: 'warn' }] }
}
function cardUptime() {
  return { title: 'Website uptime', status: 'warn', blocks: [{ type: 'table', columns: ['Site', 'Status', 'Response', 'Uptime 30 d'], rows: [
    ['www.example.com', '503', '10.0 s', '99.12 %'], ['ui.example.com', '200', '182 ms', '100 %'], ['shop.example.com', '200', '341 ms', '99.98 %']] }] }
}
function cardShop() {
  const r = rng(99), t = now()
  const pts = []
  for (let i = 13; i >= 0; i--) pts.push([fmtDay(t - i * DAY), Math.round(180 + r() * 420)])
  return { title: 'Shop sales', link: 'https://shop.example.com/admin', blocks: [
    { type: 'stats', items: [
      { label: 'Today', value: '€412', delta: '+18 %', tone: 'ok' },
      { label: 'This month', value: '€6,930', delta: '-4 %', tone: 'warn' },
      { label: 'Orders', value: 23, delta: 3, tone: 'ok' },
    ] },
    { type: 'chart', kind: 'bar', unit: '€', series: [{ name: 'Revenue', points: pts }] },
  ] }
}

/* =================================================================== system */
function healthObj() {
  const issues = []
  if (S.scenario === 'ready' || S.scenario === 'login') issues.push({ level: 'warn', code: 'disk_high', text: 'Disk usage is above 80 % (82 %)' })
  if (!S.claude.auth.ok) issues.push({ level: 'warn', code: 'claude_auth', text: 'Claude is not connected' })
  for (const s of S.services) if (s.enabled && !s.active) issues.push({ level: 'error', code: 'service_down', text: `Service ${s.name} is not running` })
  const last = S.backup.history.at(-1)
  const fails = S.loginFails.filter((x) => x > now() - HOUR).length
  if (fails >= 8) issues.push({ level: 'warn', code: 'failed_logins', text: `${fails} failed logins in the last hour` })
  const jitter = Math.sin(Date.now() / 20000)
  const disk = { total: 80e9, free: Math.round(80e9 * 0.18), pct: 82 }
  if (!(S.scenario === 'ready' || S.scenario === 'login')) { disk.free = 52e9; disk.pct = 35 }
  return { ok: !issues.some((i) => i.level === 'error'), issues, cpu_pct: +(23 + jitter * 8).toFixed(1), load: [+(0.42 + jitter * 0.1).toFixed(2), 0.38, 0.31],
    mem: { total: 8e9, avail: Math.round(3.1e9 + jitter * 2e8) }, disk, uptime_s: Math.round(now() - S.bootAt),
    claude_auth: S.claude.auth.ok, backup_age_h: last ? +((now() - last.at) / HOUR).toFixed(1) : null, failed_logins_1h: fails, at: now() }
}

function journal(unit, n) {
  const r = rng([...unit].reduce((a, c) => a + c.charCodeAt(0), 0))
  const msgs = {
    'claude-maxxing': ['INFO  GET /api/sessions 200 4ms', 'INFO  GET /api/dashboard 200 38ms', 'INFO  session %s turn finished in 41.2s', 'INFO  cron c_blog started (unit mx-cron-c_blog)', 'WARN  telegram: getUpdates timed out, retrying', 'INFO  POST /api/sessions/%s/messages 200 6ms', 'INFO  backup: pushed 41 files', 'INFO  SSE client connected (2 active)'],
    caddy: ['{"level":"info","logger":"http.log.access","msg":"handled request","status":200,"uri":"/api/stream"}', '{"level":"info","logger":"tls","msg":"certificate is valid","identifiers":["ui.example.com"]}', '{"level":"warn","logger":"http","msg":"HTTP/2 stream reset"}'],
    tailscaled: ['magicsock: derp-4 connected', 'wgengine: Reconfig: configuring router', 'netcheck: report: udp=true v6=false', 'health: state is healthy'],
    cron: ['(root) CMD (maxxing cron-run c_uptime)', 'pam_unix(cron:session): session opened for user root', 'pam_unix(cron:session): session closed for user root'],
  }[unit] || ['started', 'running', 'heartbeat ok']
  const lines = []
  const t = Date.now() - n * 37000
  for (let i = 0; i < n; i++) {
    const d = new Date(t + i * 37000)
    const ts = d.toUTCString().slice(5, 25).replace(/(\d{2}) (\w{3}) \d{4}/, '$2 $1')
    lines.push(`${ts} vps-1 ${unit}[${1200 + Math.floor(r() * 50)}]: ${msgs[Math.floor(r() * msgs.length)].replace('%s', crypto.randomUUID().slice(0, 8))}`)
  }
  return lines
}

/* =================================================================== docs */
const B = '`'
const md = (s) => s.replace(/§/g, B)
const DOCS = [
  { slug: 'getting-started', title: 'Getting started', section: 'Basics', order: 1, markdown: md(`# Getting started

Harness Maxxing runs **Claude Code** on your server and gives you a web UI, a Telegram gateway and scheduled jobs around it.

## Concepts

| Concept | What it is | Where it lives |
|---|---|---|
| Project | A group of related work | §projects/<name>/§ |
| Topic | One workflow inside a project — it is the working directory of its sessions | §projects/<name>/topics/<topic>/§ |
| Session | One Claude conversation | listed under its topic |
| Memory | Markdown files loaded automatically | §CLAUDE.md§ + §memory.md§ at each level |

## First steps

1. Connect Claude (Settings → Claude). A long-lived token from §claude setup-token§ is the easiest.
2. Create a project and a first topic.
3. Open the topic and start a [session](sessions).
4. Optionally link [Telegram](telegram) to talk to the same sessions from your phone.

## How memory is loaded

Claude Code loads every §CLAUDE.md§ from the working directory up to the workspace root, so a session in a topic receives:

- the workspace §CLAUDE.md§ (global rules),
- the project §CLAUDE.md§,
- the topic §CLAUDE.md§, which imports its §memory.md§.

§§§markdown
# Topic acme/blog

> Weekly articles for the Acme blog

@memory.md
§§§

> Keep durable facts in the **closest** §memory.md§. Short, factual, dated.

## Where next

- [Sessions](sessions) — the core of the app
- [Files](files) — browse and edit the workspace
- [Crons](crons) — run Claude on a schedule
`) },
  { slug: 'sessions', title: 'Sessions', section: 'Features', order: 2, markdown: md(`# Sessions

A session is one Claude Code conversation attached to a topic. It keeps running on the server when you close the tab.

## Starting a session

- Open a topic and click **New session**, or press §N§.
- Type a message; attach files by dropping them on the composer.
- Pick a model per session from the model menu. The badge shows the model that **actually answered** the last turn.

## While a turn runs

| Action | Effect |
|---|---|
| Send another message | It is **queued** and starts when the current turn ends |
| Stop | Interrupts the turn; the conversation stays intact |
| Clear queue | Drops waiting messages |

## Compact vs hand-off

- **Compact** summarises the conversation and continues in the *same* session with a fresh context.
- **Hand-off** creates a *new* session seeded with a summary and archives the old one.

## Notifications

Turn on **Notify** to receive a short Telegram message when a turn finishes. It is skipped if you looked at the session in the last 3 minutes.

## Search

The search box looks in titles and the last answers:

§§§text
GET /api/sessions/search?q=caddy
§§§

See also [Telegram](telegram) and [Crons](crons).
`) },
  { slug: 'files', title: 'Files', section: 'Features', order: 3, markdown: md(`# Files

The Files page shows everything under the files root (by default §/root/maxxing§).

## Features

- Browse folders, preview images and videos, download any file.
- Edit text files in place. Markdown has a live preview.
- Upload by drag and drop, create folders, move and rename.
- Deleted files go to the **trash**, never straight to oblivion.

## Conflicts

If a file changed on disk since you opened it (for example Claude edited it), saving returns a conflict and you can reload or overwrite.

## Keyboard

| Key | Action |
|---|---|
| §Ctrl+S§ | Save |
| §Ctrl+P§ | Quick open |
| §Esc§ | Close the editor |

## Linking

Any absolute path printed by Claude in a [session](sessions), like §/root/maxxing/memory.md§, becomes a link to this page.
`) },
  { slug: 'crons', title: 'Crons', section: 'Features', order: 4, markdown: md(`# Crons

Crons run on a schedule, either as a **shell command** or as a **Claude prompt** in a topic.

## Schedule syntax

Standard 5-field cron, evaluated in your timezone:

§§§text
┌ minute (0-59)
│ ┌ hour (0-23)
│ │ ┌ day of month (1-31)
│ │ │ ┌ month (1-12)
│ │ │ │ ┌ day of week (0-7, Sunday = 0 or 7)
0 7 * * *     → every day at 07:00
*/15 * * * *  → every 15 minutes
30 8 * * 1    → every Monday at 08:30
§§§

## Claude jobs

- **Topic**: working directory and memory of the run.
- **Reuse session**: append to the same session every time instead of a new one.
- **Model**: leave empty for the default.

## Notifications

| Setting | Telegram message |
|---|---|
| never | none |
| failure | only when the exit code is not 0 |
| always | every run |

Messages go to the **Crons** thread when [Telegram](telegram) topics are enabled.

## External lines

Lines of your crontab outside the managed block are listed read-only, so you can see everything that runs.
`) },
  { slug: 'telegram', title: 'Telegram', section: 'Features', order: 5, markdown: md(`# Telegram

Talk to your sessions from your phone through your own bot.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Paste it in Settings → Telegram.
3. Click **Link**, open the link and press **Start**.
4. Optional: enable **topics** to get one thread per topic, plus *General* and *Crons*.

## Threads

| Thread | Purpose |
|---|---|
| General | Sessions at the workspace root |
| Crons | Cron notifications |
| One per topic | Messages go to the latest session of that topic |

## Reply mode

- **final** — only the final answer is sent.
- **progress** — a status bubble is updated while tools run.

## Commands

§§§text
/new       start a new session in this thread's topic
/stop      stop the running turn
/sessions  list recent sessions
§§§

Sessions started from Telegram appear in the web UI with a Telegram badge — see [Sessions](sessions).
`) },
  { slug: 'extensions', title: 'Writing an extension', section: 'Extending', order: 6, markdown: md(`# Writing an extension

Extensions add **widgets** to the dashboard or full **pages** to the app. They live in §<workspace>/extensions/<id>/§.

## Manifest

§§§json
{
  "id": "shop-sales",
  "name": "Shop sales",
  "type": "widget",
  "icon": "shopping-cart",
  "version": "1.0.0",
  "span": 1,
  "ttl": 1800
}
§§§

## Widget: §api.py§

§§§python
def card(ctx):
    orders = fetch_orders()
    return {
        "title": "Shop sales",
        "blocks": [
            {"type": "stat", "label": "Today", "value": len(orders)},
        ],
    }
§§§

### Block types

| Type | Use it for |
|---|---|
| §stat§ / §stats§ | Key numbers, with optional delta and tone |
| §list§ | Short lists with status dots |
| §chart§ | §bar§ or §line§ series |
| §table§ | Small tables |
| §progress§ | A value out of a max |
| §markdown§ | Free text |

## Page: §page.js§

§§§js
export function mount(el, ctx) {
  el.textContent = 'Hello from ' + ctx.theme
  return () => { el.textContent = '' }
}
§§§

Call your §api.py§ §handle()§ with §ctx.api('path')§; it is served under §/api/ext/<id>/<path>§.

## Tips

- Keep §card()§ fast; slow widgets time out after 10 s.
- Use **Reload** in Settings → Extensions after editing files.
- Back to [Getting started](getting-started).
`) },
]

/* =================================================================== routes */
const routes = []
function R(method, pattern, handler, opts = {}) {
  const keys = []
  const re = new RegExp('^' + pattern.replace(/:(\w+)/g, (_, k) => { keys.push(k); return '([^/]+)' }).replace(/\*$/, '(.*)') + '$')
  if (pattern.endsWith('*')) keys.push('rest')
  routes.push({ method, re, keys, handler, public: !!opts.public })
}

/* ---- auth */
R('GET', '/api/auth/state', ({ authed }) => ({ setup_required: S.setup_required, authenticated: authed, version: VERSION, onboarding_completed: S.onboarding_completed, language: S.settings.language }), { public: true })

R('POST', '/api/auth/setup', ({ body, res }) => {
  if (!S.setup_required) fail(409, 'already_setup', 'Setup has already been completed')
  if (body.token !== SETUP_TOKEN) fail(403, 'bad_token', 'Invalid setup token')
  if (!body.password || String(body.password).length < 8) fail(422, 'invalid', 'Password must be at least 8 characters')
  S.password = body.password; S.setup_required = false
  setCookie(res, newToken())
  return { ok: true }
}, { public: true })

R('POST', '/api/auth/login', async ({ body, res }) => {
  if (S.setup_required) fail(409, 'setup_required', 'Run the setup first')
  const t = now()
  if (S.lockUntil > t) fail(429, 'throttled', `Too many attempts, retry in ${Math.ceil(S.lockUntil - t)} s`)
  if (body.password !== S.password) {
    await sleep(400)
    S.loginFails.push(t)
    S.failStreak = (S.failStreak || 0) + 1
    if (S.failStreak >= 5) { S.lockUntil = now() + 30; S.failStreak = 0 }
    bus('health')
    fail(401, 'bad_password', 'Wrong password')
  }
  S.failStreak = 0
  setCookie(res, newToken())
  return { ok: true }
}, { public: true })

R('POST', '/api/auth/logout', ({ req, res }) => {
  S.tokens.delete(cookieToken(req)); S.autoAuth = false
  res.setHeader('Set-Cookie', 'mx_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
  return { ok: true }
}, { public: true })

R('POST', '/api/auth/password', ({ body }) => {
  if (body.current !== S.password) fail(400, 'bad_password', 'Current password is wrong')
  if (!body.new || String(body.new).length < 8) fail(422, 'invalid', 'Password must be at least 8 characters')
  S.password = body.new
  return { ok: true }
})

/* ---- onboarding */
R('GET', '/api/onboarding', () => onboardingObj())
R('POST', '/api/onboarding/complete', () => { S.onboarding_completed = true; return { ok: true } })

/* ---- claude */
R('GET', '/api/claude/status', () => ({ ...clone(S.claude), models: MODELS }))
R('POST', '/api/claude/auth', async ({ body }) => {
  await sleep(1200)
  const v = String(body.value || '').trim()
  const kind = v.startsWith('sk-ant-oat') ? 'oauth_token' : v.startsWith('sk-ant-api') ? 'api_key' : null
  if (!kind) return { ok: false, error: 'Authentication failed: invalid token' }
  S.claude.auth = { ok: true, method: kind, detail: kind === 'oauth_token' ? 'Long-lived OAuth token (claude setup-token)' : `API key ${v.slice(0, 14)}…` }
  bus('health')
  return { ok: true }
})
R('DELETE', '/api/claude/auth', () => { S.claude.auth = { ok: false, method: null, detail: 'Not connected' }; bus('health'); return { ok: true } })
R('POST', '/api/claude/test', async () => {
  const t0 = Date.now()
  await sleep(850 + Math.floor(Math.random() * 120))
  if (!S.claude.auth.ok) return { ok: false, model: S.claude.default_model, ms: Date.now() - t0, error: 'Not authenticated — run setup-token or add an API key' }
  return { ok: true, model: S.claude.default_model, ms: Date.now() - t0 }
})
R('PUT', '/api/claude/settings', ({ body }) => {
  if (body.permission_mode !== undefined && !['bypass', 'acceptEdits', 'default'].includes(body.permission_mode)) fail(422, 'invalid', 'Unknown permission mode')
  if (body.default_model !== undefined) S.claude.default_model = String(body.default_model)
  if (body.permission_mode !== undefined) S.claude.permission_mode = body.permission_mode
  return { ok: true }
})

/* ---- workspace */
R('GET', '/api/workspace/tree', () => ({ root: ROOT, projects: S.projects.map(projectObj) }))
R('POST', '/api/workspace/projects', ({ body }) => {
  const name = String(body.name || '')
  if (!SLUG.test(name)) fail(422, 'invalid', 'Name must be lowercase letters, digits and dashes (max 48)')
  if (S.projects.some((p) => p.name === name)) fail(409, 'exists', `Project “${name}” already exists`)
  const p = { name, description: body.description || '', topics: [] }
  S.projects.push(p)
  fsAdd(S, `${projPath(name)}/CLAUDE.md`, `# Project ${name}\n\n> ${p.description}\n\n@memory.md\n`, now())
  fsAdd(S, `${projPath(name)}/memory.md`, `# ${name} — memory\n`, now())
  bus('workspace')
  return projectObj(p)
})
function renamePath(oldP, newP) {
  const remap = (x) => (x === oldP ? newP : x.startsWith(oldP + '/') ? newP + x.slice(oldP.length) : x)
  for (const s of S.sessions) s.path = remap(s.path)
  for (const th of S.telegram.threads) th.path = remap(th.path)
  for (const tk of S.tasks.tasks) if (tk.topic_path) tk.topic_path = remap(tk.topic_path)
  for (const c of S.crons) if (c.topic_path) c.topic_path = remap(c.topic_path)
  const moved = []
  for (const [k, v] of S.fs) { const nk = remap(k.slice(ROOT.length + 1)); if (k.startsWith(`${ROOT}/${oldP}`)) moved.push([k, `${ROOT}/${nk}`, v]) }
  for (const [k, nk, v] of moved) { S.fs.delete(k); S.fs.set(nk, v) }
}
function trashPath(rel) { for (const k of [...S.fs.keys()]) if (k === `${ROOT}/${rel}` || k.startsWith(`${ROOT}/${rel}/`)) S.fs.delete(k) }
R('PATCH', '/api/workspace/projects/:project', ({ params, body }) => {
  const p = findProject(params.project)
  if (body.name !== undefined && body.name !== p.name) {
    if (!SLUG.test(body.name)) fail(422, 'invalid', 'Invalid name')
    if (S.projects.some((x) => x.name === body.name)) fail(409, 'exists', 'A project with this name already exists')
    renamePath(projPath(p.name), projPath(body.name)); p.name = body.name
  }
  if (body.description !== undefined) p.description = body.description
  bus('workspace', 'sessions')
  return projectObj(p)
})
R('DELETE', '/api/workspace/projects/:project', ({ params }) => {
  const p = findProject(params.project)
  const pp = projPath(p.name)
  if (S.sessions.some((s) => s.state === 'running' && s.path.startsWith(pp + '/'))) fail(409, 'has_running_sessions', 'Stop the running sessions first')
  S.projects = S.projects.filter((x) => x !== p)
  trashPath(pp)
  bus('workspace', 'sessions')
  return { ok: true }
})
R('POST', '/api/workspace/projects/:project/topics', ({ params, body }) => {
  const p = findProject(params.project)
  const name = String(body.name || '')
  if (!SLUG.test(name)) fail(422, 'invalid', 'Name must be lowercase letters, digits and dashes (max 48)')
  if (p.topics.some((x) => x.name === name)) fail(409, 'exists', `Topic “${name}” already exists`)
  const tp = { name, description: body.description || '' }
  p.topics.push(tp)
  const base = topicPath(p.name, name)
  fsAdd(S, `${base}/CLAUDE.md`, `# Topic ${p.name}/${name}\n\n> ${tp.description}\n\n@memory.md\n`, now())
  fsAdd(S, `${base}/memory.md`, `# ${name} — memory\n`, now())
  bus('workspace')
  return topicObj(p, tp)
})
R('PATCH', '/api/workspace/projects/:project/topics/:topic', ({ params, body }) => {
  const p = findProject(params.project)
  const tp = p.topics.find((x) => x.name === params.topic) || fail(404, 'not_found', 'Topic not found')
  if (body.name !== undefined && body.name !== tp.name) {
    if (!SLUG.test(body.name)) fail(422, 'invalid', 'Invalid name')
    if (p.topics.some((x) => x.name === body.name)) fail(409, 'exists', 'A topic with this name already exists')
    renamePath(topicPath(p.name, tp.name), topicPath(p.name, body.name)); tp.name = body.name
  }
  if (body.description !== undefined) tp.description = body.description
  bus('workspace', 'sessions')
  return topicObj(p, tp)
})
R('DELETE', '/api/workspace/projects/:project/topics/:topic', ({ params }) => {
  const p = findProject(params.project)
  const tp = p.topics.find((x) => x.name === params.topic) || fail(404, 'not_found', 'Topic not found')
  const tpp = topicPath(p.name, tp.name)
  if (S.sessions.some((s) => s.state === 'running' && s.path === tpp)) fail(409, 'has_running_sessions', 'Stop the running sessions first')
  p.topics = p.topics.filter((x) => x !== tp)
  trashPath(tpp)
  bus('workspace', 'sessions')
  return { ok: true }
})

/* ---- sessions */
R('POST', '/api/sessions/:id/queue/take', ({ params }) => {
  const s = S.sessions.find((x) => x.id === params.id) || fail(404, 'not_found', 'Session not found')
  const n = s.queue; s.queue = 0; bus('sessions')
  return { messages: Array.from({ length: n }, (_, i) => ({ text: `Queued message ${i + 1}`, attachments: [] })), session: s }
})
R('POST', '/api/sessions/:id/steer', ({ params }) => {
  const s = S.sessions.find((x) => x.id === params.id) || fail(404, 'not_found', 'Session not found')
  const steered = s.state === 'running' && s.queue > 0
  if (steered) { s.queue = 1; bus('sessions') }
  return { steered, interrupted: steered, session: s }
})
R('GET', '/api/search', ({ q }) => {
  const term = (q.get('q') || '').trim().toLowerCase()
  if (term.length < 2) return { results: [], took_ms: 0 }
  const mark = (txt) => { const i = txt.toLowerCase().indexOf(term); return i < 0 ? txt.slice(0, 120) : txt.slice(Math.max(0, i - 40), i) + '\u0002' + txt.slice(i, i + term.length) + '\u0003' + txt.slice(i + term.length, i + term.length + 60) }
  const results = []
  for (const s of S.sessions) {
    const e = (S.events[s.id] || []).find((x) => (x.type === 'assistant' || x.type === 'user') && x.text.toLowerCase().includes(term))
    if (e || s.title.toLowerCase().includes(term)) results.push({ kind: 'session', id: s.id, path: s.path, title: s.title, snippet: e ? mark(e.text.replace(/\n/g, ' ')) : s.title, at: s.updated, score: 1 })
  }
  for (const tk of S.tasks.tasks) if ((tk.title + ' ' + tk.notes).toLowerCase().includes(term)) results.push({ kind: 'task', id: tk.id, path: '', title: tk.title, snippet: mark(tk.title + ' ' + tk.notes), at: tk.updated, score: 1 })
  return { results: results.slice(0, 30), took_ms: 1.2 }
})
R('GET', '/api/sessions/search', ({ q }) => {
  const term = (q.get('q') || '').trim().toLowerCase()
  if (!term) return []
  const hits = []
  for (const s of S.sessions) {
    const inTitle = s.title.toLowerCase().includes(term)
    let snippet = null
    const lt = s.last_text, i = lt.toLowerCase().indexOf(term)
    if (i !== -1) snippet = (i > 40 ? '…' : '') + lt.slice(Math.max(0, i - 40), i + term.length + 60) + (i + term.length + 60 < lt.length ? '…' : '')
    else {
      const e = (S.events[s.id] || []).find((x) => (x.type === 'assistant' || x.type === 'user') && x.text.toLowerCase().includes(term))
      if (e) { const j = e.text.toLowerCase().indexOf(term); snippet = '…' + e.text.slice(Math.max(0, j - 40), j + term.length + 60).replace(/\n/g, ' ') + '…' }
    }
    if (inTitle || snippet) hits.push({ id: s.id, title: s.title, path: s.path, snippet: snippet || lt.slice(0, 100), at: s.updated })
  }
  return hits.sort((a, b) => b.at - a.at).slice(0, 50)
})
R('GET', '/api/sessions', ({ q }) => {
  const pth = q.get('path')
  const arch = q.get('archived') === '1'
  return S.sessions.filter((s) => (pth === null || s.path === pth) && s.archived === arch).sort((a, b) => b.updated - a.updated)
})
R('POST', '/api/sessions', ({ body }) => {
  if (typeof body.path !== 'string') fail(422, 'invalid', 'path is required')
  const t = now()
  const msg = (body.message || '').trim()
  const s = { id: uuid(), title: body.title || (msg ? msg.slice(0, 60) : 'New session'), path: body.path, state: 'idle', queue: 0, created: t, updated: t, turns: 0, cost_usd: 0,
    model: body.model || '', real_model: null, context_tokens: null, context_window: null, archived: false, notify: false, source: 'web', unread: false, last_text: '', error: null }
  S.sessions.push(s); S.events[s.id] = []
  if (msg) startTurn(s, msg, body.attachments || [])
  bus('sessions', 'workspace')
  return s
})
R('GET', '/api/sessions/:id', ({ params }) => findSession(params.id))
R('PATCH', '/api/sessions/:id', ({ params, body }) => {
  const s = findSession(params.id)
  for (const k of ['title', 'model', 'archived', 'notify', 'plan_mode']) if (body[k] !== undefined) s[k] = body[k]
  if (body.plan_mode === false) s.plan_ready = false
  if (body.archived === true) addEvents(s, { type: 'note', text: 'Session archived.', level: 'info', at: now() })
  bus('sessions', 'workspace')
  pushEvents(s.id, [])
  return s
})
R('DELETE', '/api/sessions/:id', ({ params }) => {
  const s = findSession(params.id)
  clearTimers(s)
  S.sessions = S.sessions.filter((x) => x !== s); delete S.events[s.id]; delete S.queues[s.id]
  bus('sessions', 'workspace')
  return { ok: true }
})
R('POST', '/api/sessions/:id/messages', ({ params, body }) => {
  const s = findSession(params.id)
  const text = String(body.text || '').trim()
  if (!text) fail(422, 'invalid', 'Message is empty')
  if (s.archived) s.archived = false
  if (s.state === 'running') {
    (S.queues[s.id] ||= []).push({ text, attachments: body.attachments || [] })
    s.queue = S.queues[s.id].length
    bus('sessions')
    pushEvents(s.id, [])
    return { queued: true, session: s }
  }
  startTurn(s, text, body.attachments || [])
  return { queued: false, session: s }
})
R('POST', '/api/sessions/:id/plan/approve', ({ params, body }) => {
  const s = findSession(params.id)
  if (s.state === 'running') fail(409, 'running', 'A turn is running')
  s.plan_mode = false; s.plan_ready = false
  startTurn(s, String(body.text || '').trim() || 'The plan is validated: carry it out.', [])
  return { queued: false, session: s }
})
R('DELETE', '/api/sessions/:id/queue', ({ params }) => {
  const s = findSession(params.id)
  S.queues[s.id] = []; s.queue = 0
  bus('sessions'); pushEvents(s.id, [])
  return { ok: true }
})
R('POST', '/api/sessions/:id/stop', ({ params }) => {
  const s = findSession(params.id)
  if (s.state === 'running') {
    clearTimers(s)
    s.state = 'idle'; s.updated = now()
    addEvents(s, { type: 'note', text: 'Turn stopped by user.', level: 'warn', at: now() })
    bus('sessions', 'workspace')
  }
  return { ok: true }
})
R('POST', '/api/sessions/:id/compact', async ({ params }) => {
  const s = findSession(params.id)
  if (s.state === 'running') fail(409, 'busy', 'Wait for the turn to finish')
  await sleep(1500)
  s.context_tokens = 4200; s.updated = now()
  addEvents(s, { type: 'note', text: 'Context compacted — the next turn starts from a summary of this conversation.', level: 'info', at: now() })
  bus('sessions')
  return { ok: true }
})
R('POST', '/api/sessions/:id/handoff', async ({ params }) => {
  const s = findSession(params.id)
  await sleep(1200)
  const t = now()
  const n = { ...s, id: uuid(), title: `${s.title} (continued)`, state: 'idle', queue: 0, created: t, updated: t, turns: 0, cost_usd: 0, real_model: null, context_tokens: 3800, archived: false, unread: false, error: null }
  S.sessions.push(n)
  S.events[n.id] = [
    { type: 'note', text: `Handed off from “${s.title}”.`, level: 'info', at: t },
    { type: 'user', text: `Summary of the previous session:\n\n- Goal: ${s.title}\n- Status: ${s.last_text}\n\nContinue from here.`, attachments: [], at: t, source: 'web' },
  ]
  s.archived = true
  addEvents(s, { type: 'note', text: 'Handed off to a new session; this one is archived.', level: 'info', at: t })
  bus('sessions', 'workspace')
  return n
})
R('POST', '/api/sessions/:id/seen', ({ params }) => {
  const s = findSession(params.id)
  if (s.unread) { s.unread = false; bus('sessions', 'workspace') }
  return { ok: true }
})
R('GET', '/api/sessions/:id/events', ({ params, q }) => {
  const s = findSession(params.id)
  const ev = S.events[s.id] || []
  const from = Math.max(0, Math.min(ev.length, parseInt(q.get('from') || '0', 10) || 0))
  return { events: ev.slice(from), next: ev.length, state: s.state }
})
R('GET', '/api/sessions/:id/stream', ({ params, q, req, res }) => {
  const s = findSession(params.id)
  const ev = S.events[s.id] || []
  const from = Math.max(0, Math.min(ev.length, parseInt(q.get('from') || '0', 10) || 0))
  sseOpen(req, res)
  sseSend(res, 'events', { events: ev.slice(from), next: ev.length })
  sseSend(res, 'state', s)
  let set = sessionSubs.get(s.id)
  if (!set) sessionSubs.set(s.id, (set = new Set()))
  set.add(res)
  req.on('close', () => set.delete(res))
  return RAW
})
R('POST', '/api/uploads', ({ q, req, rawBody }) => {
  const topic = q.get('path') || ''
  const files = parseMultipart(rawBody, req.headers['content-type'] || '')
  if (!files.length) fail(422, 'invalid', 'No file in the request')
  const d = new Date()
  const dir = `${ROOT}/${topic ? topic + '/' : ''}attachments/${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`
  const out = files.map((f) => {
    const p = uniquePath(`${dir}/${f.name}`)
    fsAdd(S, p, isText(f.mime) ? f.data.toString('utf8') : f.data, now(), f.mime)
    return { path: p, name: path.basename(p), size: f.data.length, mime: f.mime }
  })
  return { files: out }
})

/* ---- global bus */
R('GET', '/api/stream', ({ req, res }) => {
  sseOpen(req, res)
  busClients.add(res)
  req.on('close', () => busClients.delete(res))
  return RAW
})

/* ---- files */
function absPath(p, { must = true } = {}) {
  const raw = p == null || p === '' ? ROOT : String(p)
  const abs = path.posix.normalize(raw.startsWith('/') ? raw : `${ROOT}/${raw}`).replace(/\/$/, '') || '/'
  if (abs !== ROOT && !abs.startsWith(ROOT + '/')) fail(403, 'outside_root', `Path must be inside ${ROOT}`)
  if (must && !S.fs.has(abs)) fail(404, 'not_found', 'No such file or directory')
  return abs
}
function uniquePath(p) {
  if (!S.fs.has(p)) return p
  const ext = path.extname(p), base = p.slice(0, p.length - ext.length)
  for (let i = 1; ; i++) if (!S.fs.has(`${base}-${i}${ext}`)) return `${base}-${i}${ext}`
}
const entryOf = (abs, n) => ({ name: path.basename(abs), path: abs, type: n.type, size: n.size, mtime: n.mtime, mime: n.type === 'dir' ? 'inode/directory' : n.mime })

R('GET', '/api/files/list', ({ q }) => {
  const abs = absPath(q.get('path'))
  const node = S.fs.get(abs)
  if (node.type !== 'dir') fail(400, 'not_a_directory', 'Not a directory')
  const entries = []
  for (const [k, n] of S.fs) if (k !== abs && path.posix.dirname(k) === abs) entries.push(entryOf(k, n))
  entries.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'dir' ? -1 : 1))
  return { path: abs, parent: abs === ROOT ? null : path.posix.dirname(abs), root: ROOT, entries }
})
R('GET', '/api/files/read', ({ q }) => {
  const abs = absPath(q.get('path'))
  const n = S.fs.get(abs)
  if (n.type === 'dir') fail(400, 'is_a_directory', 'This is a directory')
  if (n.size > 2 * 1024 * 1024) fail(413, 'too_large', 'File is larger than 2 MB')
  const text = isText(n.mime) && typeof n.content === 'string' && !n.mime.startsWith('image/')
  if (!text) fail(415, 'binary', 'Binary file — use /api/files/raw')
  return { path: abs, content: n.content, mtime: n.mtime, size: n.size, mime: n.mime, editable: true }
})
R('GET', '/api/files/raw', ({ q, req, res }) => {
  const abs = absPath(q.get('path'))
  const n = S.fs.get(abs)
  if (n.type === 'dir') fail(400, 'is_a_directory', 'This is a directory')
  let mime = n.mime, body = n.content
  if (mime.startsWith('image/') && typeof body === 'string' && body.startsWith('<svg')) mime = 'image/svg+xml'
  if (typeof body === 'string') body = Buffer.from(body)
  const headers = { 'Content-Type': mime, 'Cache-Control': 'no-store', 'Accept-Ranges': 'bytes' }
  if (q.get('download') === '1') headers['Content-Disposition'] = `attachment; filename="${path.basename(abs)}"`
  const range = req.headers.range && /^bytes=(\d*)-(\d*)$/.exec(req.headers.range)
  if (range) {
    const start = range[1] ? +range[1] : 0, end = range[2] ? Math.min(+range[2], body.length - 1) : body.length - 1
    res.writeHead(206, { ...headers, 'Content-Range': `bytes ${start}-${end}/${body.length}`, 'Content-Length': end - start + 1 })
    res.end(body.subarray(start, end + 1))
  } else {
    res.writeHead(200, { ...headers, 'Content-Length': body.length })
    res.end(body)
  }
  return RAW
})
R('GET', '/api/files/thumb', ({ q, res }) => {
  const abs = absPath(q.get('path'))
  const w = Math.min(1024, Math.max(32, parseInt(q.get('w') || '320', 10) || 320))
  const svg = PLACEHOLDER_SVG(path.basename(abs), w, Math.round(w * 0.625))
  res.writeHead(200, { 'Content-Type': 'image/svg+xml', 'Cache-Control': 'private, max-age=3600' })
  res.end(svg)
  return RAW
})
R('PUT', '/api/files/write', ({ body }) => {
  const abs = absPath(body.path, { must: false })
  const n = S.fs.get(abs)
  if (n && n.type === 'dir') fail(400, 'is_a_directory', 'This is a directory')
  if (n && body.expected_mtime != null && Math.abs(n.mtime - body.expected_mtime) > 0.001) fail(409, 'conflict', 'The file changed on disk since you opened it')
  const mtime = now()
  fsAdd(S, abs, String(body.content ?? ''), mtime, n ? n.mime : undefined)
  return { ok: true, mtime }
})
R('POST', '/api/files/mkdir', ({ body }) => {
  const abs = absPath(body.path, { must: false })
  if (S.fs.has(abs)) fail(409, 'exists', 'Already exists')
  fsMkdirp(S, abs)
  return { ok: true }
})
R('POST', '/api/files/move', ({ body }) => {
  const from = absPath(body.from), to = absPath(body.to, { must: false })
  if (from === ROOT) fail(403, 'forbidden', 'Cannot move the root')
  if (S.fs.has(to)) fail(409, 'exists', 'Destination already exists')
  fsMkdirp(S, path.posix.dirname(to))
  for (const [k, v] of [...S.fs]) if (k === from || k.startsWith(from + '/')) { S.fs.delete(k); S.fs.set(to + k.slice(from.length), v) }
  return { ok: true }
})
R('POST', '/api/files/delete', ({ body }) => {
  const abs = absPath(body.path)
  if (abs === ROOT) fail(403, 'forbidden', 'Cannot delete the root')
  for (const k of [...S.fs.keys()]) if (k === abs || k.startsWith(abs + '/')) S.fs.delete(k)
  return { ok: true }
})
R('POST', '/api/files/upload', ({ q, req, rawBody }) => {
  const dir = absPath(q.get('dir'))
  const files = parseMultipart(rawBody, req.headers['content-type'] || '')
  if (!files.length) fail(422, 'invalid', 'No file in the request')
  return { files: files.map((f) => {
    const p = uniquePath(`${dir}/${f.name}`)
    fsAdd(S, p, isText(f.mime) ? f.data.toString('utf8') : f.data, now(), f.mime)
    return { path: p, name: path.basename(p), size: f.data.length, mime: f.mime }
  }) }
})
R('GET', '/api/files/search', ({ q }) => {
  const term = (q.get('q') || '').trim().toLowerCase()
  if (!term) return []
  const out = []
  for (const [k, n] of S.fs) if (k !== ROOT && k.slice(ROOT.length).toLowerCase().includes(term)) out.push({ path: k, name: path.basename(k), type: n.type })
  return out.sort((a, b) => a.path.length - b.path.length).slice(0, 50)
})

/* ---- tasks */
const TASK_FIELDS = ['title', 'notes', 'status', 'priority', 'due', 'project_id', 'topic_path', 'labels', 'order']
function applyTask(tk, body) {
  for (const k of TASK_FIELDS) if (body[k] !== undefined) tk[k] = body[k]
  if (body.status !== undefined && !['todo', 'doing', 'done'].includes(body.status)) fail(422, 'invalid', 'Unknown status')
  if (body.priority !== undefined && ![0, 1, 2, 3].includes(body.priority)) fail(422, 'invalid', 'Priority must be 0-3')
  if (body.due != null && body.due !== undefined && !/^\d{4}-\d{2}-\d{2}$/.test(body.due)) fail(422, 'invalid', 'due must be YYYY-MM-DD')
  if (body.status !== undefined) tk.done_at = body.status === 'done' ? tk.done_at || now() : null
  tk.updated = now()
}
R('GET', '/api/tasks', () => S.tasks)
R('POST', '/api/tasks', ({ body }) => {
  if (!body.title || !String(body.title).trim()) fail(422, 'invalid', 'title is required')
  const t = now()
  const tk = { id: rid('t'), title: '', notes: '', status: 'todo', priority: 0, due: null, project_id: null, topic_path: null, labels: [], created: t, updated: t, done_at: null,
    order: Math.max(0, ...S.tasks.tasks.map((x) => x.order)) + 1000 }
  applyTask(tk, body)
  S.tasks.tasks.push(tk)
  bus('tasks')
  return tk
})
R('POST', '/api/tasks/projects', ({ body }) => {
  if (!body.name) fail(422, 'invalid', 'name is required')
  const p = { id: rid('tp'), name: String(body.name), color: body.color || '#64748b' }
  S.tasks.projects.push(p); bus('tasks')
  return p
})
R('PATCH', '/api/tasks/projects/:id', ({ params, body }) => {
  const p = S.tasks.projects.find((x) => x.id === params.id) || fail(404, 'not_found', 'Task project not found')
  if (body.name !== undefined) p.name = body.name
  if (body.color !== undefined) p.color = body.color
  bus('tasks')
  return p
})
R('DELETE', '/api/tasks/projects/:id', ({ params }) => {
  const p = S.tasks.projects.find((x) => x.id === params.id) || fail(404, 'not_found', 'Task project not found')
  S.tasks.projects = S.tasks.projects.filter((x) => x !== p)
  for (const tk of S.tasks.tasks) if (tk.project_id === p.id) tk.project_id = null
  bus('tasks')
  return { ok: true }
})
R('POST', '/api/tasks/bulk', ({ body }) => {
  const ids = new Set(body.ids || [])
  if (!ids.size) fail(400, 'invalid_ids', 'ids must list at least one task id')
  const hit = S.tasks.tasks.filter((x) => ids.has(x.id))
  if (body.delete) {
    S.tasks.tasks = S.tasks.tasks.filter((x) => !ids.has(x.id)); bus('tasks')
    return { ok: true, updated: 0, deleted: hit.length }
  }
  for (const tk of hit) {
    applyTask(tk, body.patch || {})
    if (body.labels_remove) tk.labels = tk.labels.filter((l) => !body.labels_remove.includes(l))
    for (const l of body.labels_add || []) if (!tk.labels.includes(l)) tk.labels.push(l)
  }
  bus('tasks')
  return { ok: true, updated: hit.length, deleted: 0 }
})
R('PATCH', '/api/tasks/:id', ({ params, body }) => {
  const tk = S.tasks.tasks.find((x) => x.id === params.id) || fail(404, 'not_found', 'Task not found')
  applyTask(tk, body); bus('tasks')
  return tk
})
R('DELETE', '/api/tasks/:id', ({ params }) => {
  const tk = S.tasks.tasks.find((x) => x.id === params.id) || fail(404, 'not_found', 'Task not found')
  S.tasks.tasks = S.tasks.tasks.filter((x) => x !== tk); bus('tasks')
  return { ok: true }
})

/* ---- crons */
const CRON_FIELDS = ['name', 'schedule', 'kind', 'command', 'topic_path', 'prompt', 'model', 'reuse_session', 'enabled', 'notify', 'timeout_s']
function applyCron(c, body) {
  for (const k of CRON_FIELDS) if (body[k] !== undefined) c[k] = body[k]
  if (!c.name) fail(422, 'invalid', 'name is required')
  if (!cronValid(c.schedule)) fail(422, 'invalid_schedule', `Invalid cron expression “${c.schedule}”`)
  if (!['shell', 'claude'].includes(c.kind)) fail(422, 'invalid', 'kind must be shell or claude')
  if (c.kind === 'shell' && !c.command) fail(422, 'invalid', 'command is required for shell jobs')
  if (c.kind === 'claude' && !c.prompt) fail(422, 'invalid', 'prompt is required for Claude jobs')
  if (!['never', 'failure', 'always'].includes(c.notify)) fail(422, 'invalid', 'Unknown notify mode')
}
R('GET', '/api/crons', () => ({ jobs: S.crons.map(cronOut), external: S.external }))
R('GET', '/api/crons/runs', ({ q }) => {
  const cid = q.get('cron_id'), limit = Math.min(500, parseInt(q.get('limit') || '50', 10) || 50)
  return S.cronRuns.filter((r) => !cid || r.cron_id === cid).slice(0, limit)
})
R('GET', '/api/crons/preview', ({ q }) => {
  const sch = (q.get('schedule') || '').trim()
  const valid = cronValid(sch)
  return { valid, human: valid ? cronHuman(sch) : 'Invalid expression — expected 5 fields: minute hour day month weekday', next: valid ? cronNext(sch, 5) : [] }
})
R('POST', '/api/crons', ({ body }) => {
  const c = { id: rid('c'), name: '', schedule: '', kind: 'shell', command: '', topic_path: '', prompt: '', model: '', reuse_session: false, enabled: true, notify: 'failure', timeout_s: 600, last_run: null }
  applyCron(c, body)
  S.crons.push(c); bus('crons')
  return cronOut(c)
})
R('PATCH', '/api/crons/:id', ({ params, body }) => {
  const c = S.crons.find((x) => x.id === params.id) || fail(404, 'not_found', 'Cron not found')
  const copy = { ...c }
  applyCron(copy, body)
  Object.assign(c, copy); bus('crons')
  return cronOut(c)
})
R('DELETE', '/api/crons/:id', ({ params }) => {
  const c = S.crons.find((x) => x.id === params.id) || fail(404, 'not_found', 'Cron not found')
  S.crons = S.crons.filter((x) => x !== c); bus('crons')
  return { ok: true }
})
R('POST', '/api/crons/:id/run', ({ params }) => {
  const c = S.crons.find((x) => x.id === params.id) || fail(404, 'not_found', 'Cron not found')
  const g = GEN, started = now()
  let sid = null
  if (c.kind === 'claude') {
    const s = { id: uuid(), title: `${c.name} — manual run`, path: c.topic_path, state: 'idle', queue: 0, created: started, updated: started, turns: 0, cost_usd: 0,
      model: c.model, real_model: null, context_tokens: null, context_window: null, archived: false, notify: c.notify !== 'never', source: 'cron', unread: false, last_text: '', error: null }
    S.sessions.push(s); S.events[s.id] = []; sid = s.id
    startTurn(s, c.prompt)
  }
  setTimeout(() => {
    if (g !== GEN) return
    const ok = c.id !== 'c_uptime'
    const dur = +(now() - started).toFixed(1)
    c.last_run = { at: started, ok, code: ok ? 0 : 22, duration_s: dur }
    S.cronRuns.unshift({ id: rid('r'), cron_id: c.id, name: c.name, at: started, ok, code: c.last_run.code, duration_s: dur,
      output_tail: ok ? 'Done.' : 'curl: (22) The requested URL returned error: 503', session_id: sid })
    bus('crons', 'health')
  }, c.kind === 'claude' ? 3600 : 1500)
  bus('crons')
  return { ok: true }
})

/* ---- telegram */
function tgStatus() {
  const tg = S.telegram
  return { configured: !!tg.token, running: !!tg.token && !!tg.chat, bot: tg.bot, chat: tg.chat, topics_enabled: tg.topics_enabled, threads: tg.threads, settings: tg.settings, linking: !!tg.link && !tg.chat, last_error: tg.last_error }
}
R('GET', '/api/telegram', () => tgStatus())
R('POST', '/api/telegram/token', async ({ body }) => {
  await sleep(600)
  const token = String(body.token || '').trim()
  if (!/^\d+:[\w-]{30,}$/.test(token)) return { ok: false, error: 'Unauthorized: invalid bot token' }
  const bot = { id: parseInt(token.split(':')[0], 10), username: 'acme_maxxing_bot', name: 'Acme Maxxing' }
  Object.assign(S.telegram, { token, bot, last_error: null })
  bus('telegram')
  return { ok: true, bot }
})
R('POST', '/api/telegram/link', () => {
  if (!S.telegram.token) fail(409, 'not_configured', 'Set the bot token first')
  const code = crypto.randomBytes(5).toString('hex')
  S.telegram.link = { code, at: Date.now() }
  return { code, deep_link: `https://t.me/${S.telegram.bot.username}?start=${code}` }
})
R('GET', '/api/telegram/link', () => {
  const tg = S.telegram
  if (!tg.chat && tg.link && Date.now() - tg.link.at >= 6000) {
    tg.chat = { id: 123456789, title: 'Alex', type: 'private' }
    tg.link = null
    bus('telegram')
  }
  return { linked: !!tg.chat, chat: tg.chat }
})
R('POST', '/api/telegram/sync', async () => {
  if (!S.telegram.chat) fail(409, 'not_linked', 'Link a chat first')
  await sleep(500)
  const want = makeThreads(S)
  let created = 0
  let maxId = Math.max(100, ...S.telegram.threads.map((x) => x.thread_id))
  for (const w of want) if (!S.telegram.threads.some((x) => x.path === w.path)) { S.telegram.threads.push({ ...w, thread_id: w.thread_id < 100 ? w.thread_id : ++maxId }); created++ }
  S.telegram.topics_enabled = true
  bus('telegram', 'workspace')
  return { created, topics_enabled: S.telegram.topics_enabled, error: null }
})
R('PUT', '/api/telegram/settings', ({ body }) => {
  const st = S.telegram.settings
  if (body.reply_mode !== undefined && !['final', 'progress'].includes(body.reply_mode)) fail(422, 'invalid', 'reply_mode must be final or progress')
  for (const k of ['notify_crons', 'login_alerts', 'reply_mode']) if (body[k] !== undefined) st[k] = body[k]
  bus('telegram')
  return { ok: true }
})
R('POST', '/api/telegram/test', async () => {
  if (!S.telegram.chat) fail(409, 'not_linked', 'Link a chat first')
  await sleep(500)
  return { ok: true }
})
R('DELETE', '/api/telegram', () => {
  Object.assign(S.telegram, { token: null, bot: null, chat: null, topics_enabled: false, threads: [], last_error: null, link: null })
  bus('telegram', 'workspace')
  return { ok: true }
})

/* ---- backup */
function backupStatus() {
  const b = S.backup
  return { configured: b.configured, repo: b.repo, private: b.private, schedule: b.schedule, include: b.include, always: b.always, last: b.history.at(-1) || null }
}
R('GET', '/api/backup', () => backupStatus())
R('POST', '/api/backup/config', async ({ body }) => {
  await sleep(900)
  const repo = String(body.repo || '').trim(), token = String(body.token || '').trim()
  if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) return { ok: false, private: false, error: 'Repository must look like owner/name' }
  if (!token.startsWith('github_pat_')) return { ok: false, private: false, error: 'Bad credentials: use a fine-grained token (github_pat_…)' }
  Object.assign(S.backup, { configured: true, repo, private: true })
  bus('backup', 'health')
  return { ok: true, private: true }
})
R('PUT', '/api/backup/settings', ({ body }) => {
  if (body.schedule !== undefined) { if (!cronValid(body.schedule)) fail(422, 'invalid_schedule', 'Invalid cron expression'); S.backup.schedule = body.schedule }
  if (body.include !== undefined) { if (!Array.isArray(body.include)) fail(422, 'invalid', 'include must be a list'); S.backup.include = body.include }
  bus('backup')
  return { ok: true }
})
R('POST', '/api/backup/run', async () => {
  if (!S.backup.configured) fail(409, 'not_configured', 'Configure the backup repository first')
  await sleep(1500)
  const run = { at: now(), ok: true, commit: sha().slice(0, 7), files: 42, error: null }
  S.backup.history.push(run)
  bus('backup', 'health')
  return { ok: true, commit: run.commit, files: run.files }
})
R('GET', '/api/backup/history', () => [...S.backup.history].reverse())
R('POST', '/api/backup/restore', async ({ body }) => {
  if (!S.backup.configured) fail(409, 'not_configured', 'Configure the backup repository first')
  await sleep(1200)
  return { ok: true, ref: body.ref || 'HEAD', files: 42, trash: `${ROOT}/.trash/restore-${Math.floor(now())}` }
})
R('DELETE', '/api/backup', () => {
  Object.assign(S.backup, { configured: false, repo: null, private: null })
  bus('backup', 'health')
  return { ok: true }
})

/* ---- settings & secrets */
R('GET', '/api/settings', () => S.settings)
R('PUT', '/api/settings', ({ body }) => {
  if (body.language !== undefined && !['en', 'fr'].includes(body.language)) fail(422, 'invalid', 'language must be en or fr')
  if (body.public_url !== undefined && body.public_url && !/^https?:\/\//.test(body.public_url)) fail(422, 'invalid', 'public_url must start with http(s)://')
  for (const k of ['timezone', 'language', 'public_url', 'files_root', 'presentation_default', 'usage_widget', 'memory_max_lines', 'donation_hidden']) if (body[k] !== undefined) S.settings[k] = body[k]
  return S.settings
})
const secretOut = (s) => ({ name: s.name, note: s.note, expose: s.expose, updated: s.updated, preview: s.value.slice(0, 4) + '…' })
R('GET', '/api/secrets', () => S.secrets.map(secretOut))
R('PUT', '/api/secrets/:name', ({ params, body }) => {
  const name = decodeURIComponent(params.name)
  if (!/^[A-Z][A-Z0-9_]{0,63}$/.test(name)) fail(422, 'invalid', 'Name must be UPPER_SNAKE_CASE')
  let s = S.secrets.find((x) => x.name === name)
  if (!s) {
    if (!body.value) fail(422, 'invalid', 'value is required for a new secret')
    s = { name, note: '', expose: false, value: '', updated: now() }
    S.secrets.push(s)
  }
  if (body.value !== undefined) s.value = String(body.value)
  if (body.note !== undefined) s.note = String(body.note)
  if (body.expose !== undefined) s.expose = !!body.expose
  s.updated = now()
  return { ok: true }
})
R('GET', '/api/secrets/:name/reveal', ({ params }) => {
  const s = S.secrets.find((x) => x.name === params.name) || fail(404, 'not_found', 'Secret not found')
  return { value: s.value }
})
R('DELETE', '/api/secrets/:name', ({ params }) => {
  const s = S.secrets.find((x) => x.name === params.name) || fail(404, 'not_found', 'Secret not found')
  S.secrets = S.secrets.filter((x) => x !== s)
  return { ok: true }
})

/* ---- system */
R('GET', '/api/system/health', () => healthObj())
R('GET', '/api/system/services', () => S.services)
R('POST', '/api/system/services/:name/:action', async ({ params }) => {
  const s = S.services.find((x) => x.name === params.name) || fail(404, 'not_found', 'Unknown service')
  if (!['start', 'stop', 'restart'].includes(params.action)) fail(404, 'not_found', 'Unknown action')
  if (s.name === 'claude-maxxing' && params.action === 'stop') fail(409, 'self', 'Stopping the UI service from the UI is not allowed')
  await sleep(500)
  if (params.action === 'stop') { s.active = false; s.since = null } else { s.active = true; s.since = now() }
  bus('health')
  return { ok: true }
})
R('GET', '/api/system/logs', ({ q }) => {
  const unit = q.get('unit') || 'claude-maxxing'
  if (!S.services.some((s) => s.name === unit)) fail(404, 'not_found', 'Unknown unit')
  const n = Math.min(2000, Math.max(1, parseInt(q.get('lines') || '200', 10) || 200))
  return { lines: journal(unit, n) }
})
R('GET', '/api/system/version', () => ({ version: VERSION, commit: 'a1b2c3d', latest_commit: 'e4f5a6b', behind: 3 }))
R('POST', '/api/system/update', () => ({ ok: true }))
R('GET', '/api/system/changelog', () => ({ version: VERSION, entries: [
  { version: VERSION, label: 'unreleased', current: true, body: '- **Bulk task actions**: select several tasks and change them at once.\n- **Notifications** when Claude finishes.' },
  { version: '1.9.0', label: '', current: false, body: '- Earlier release.' },
] }))
R('GET', '/api/memory', () => ({ max_lines: S.settings.memory_max_lines ?? 200, files: [
  { path: 'memory.md', level: 'global', lines: 42, bytes: 2100, over: false },
  { path: 'projects/acme/memory.md', level: 'project', lines: 260, bytes: 14000, over: (S.settings.memory_max_lines ?? 200) > 0 && 260 > (S.settings.memory_max_lines ?? 200) },
  { path: 'projects/acme/topics/blog/memory.md', level: 'topic', lines: 80, bytes: 4100, over: false },
] }))
R('POST', '/api/memory/compact', () => ({ session: S.sessions[0] || null }))
R('GET', '/api/stats/tokens', () => {
  const row = (total) => ({ input: Math.round(total * 0.05), output: Math.round(total * 0.05), cache_read: Math.round(total * 0.85), cache_write: Math.round(total * 0.05), total, cost_usd: total / 400000, turns: Math.round(total / 50000), sessions: 3 })
  const days = Array.from({ length: 30 }, (_, i) => ({ date: new Date(Date.now() - (29 - i) * 864e5).toISOString().slice(0, 10), tokens: 200000 + ((i * 7919) % 9) * 90000, cost_usd: 1.2 }))
  return { totals: row(12_500_000), projects: [{ name: 'acme', ...row(9_000_000) }, { name: '', ...row(3_500_000) }],
    topics: [{ path: 'projects/acme/topics/blog', ...row(6_000_000) }, { path: 'projects/acme/topics/shop', ...row(3_000_000) }],
    sessions: (S.sessions || []).slice(0, 5).map((x, i) => ({ id: x.id, title: x.title, path: x.path, archived: false, updated: x.updated, ...row(2_000_000 - i * 300_000) })),
    days, at: now() }
})
R('GET', '/api/usage', () => ({ available: false, five_hour: null, seven_day: null, reason: 'disabled' }))

/* ---- docs */
R('GET', '/api/docs', () => DOCS.map(({ slug, title, section, order }) => ({ slug, title, section, order })))
R('GET', '/api/docs/:slug', ({ params }) => {
  const d = DOCS.find((x) => x.slug === params.slug) || fail(404, 'not_found', 'No such doc page')
  return { slug: d.slug, title: d.title, markdown: d.markdown }
})

/* ---- dashboard & extensions */
R('GET', '/api/dashboard', () => dashboard())
R('GET', '/api/dashboard/widgets/:id', async ({ params, q }) => {
  const d = widgetDefs().find((x) => x.id === params.id) || fail(404, 'not_found', 'Unknown widget')
  if (q.get('force') === '1') {
    await sleep(params.id === 'uptime' ? 900 : 300)
    S.widgetUpdated[d.id] = now()
    if (d.id === 'uptime') S.uptimeFixed = true
  }
  return renderWidget(d)
})
R('PUT', '/api/dashboard/layout', ({ body }) => {
  if (!Array.isArray(body.order) || !Array.isArray(body.hidden)) fail(422, 'invalid', 'order and hidden must be lists')
  S.layout = { order: body.order.map(String), hidden: body.hidden.map(String) }
  return { ok: true }
})
R('GET', '/api/extensions', () => S.extensions)
R('PATCH', '/api/extensions/:id', ({ params, body }) => {
  const e = S.extensions.find((x) => x.id === params.id) || fail(404, 'not_found', 'Unknown extension')
  if (typeof body.enabled !== 'boolean') fail(422, 'invalid', 'enabled must be a boolean')
  if (body.enabled && e.error) fail(409, 'broken', `Cannot enable: ${e.error}`)
  e.enabled = body.enabled
  bus('extensions')
  return { ok: true }
})
R('POST', '/api/extensions/reload', async () => { await sleep(400); bus('extensions'); return { ok: true, count: S.extensions.length } })
for (const m of ['GET', 'POST', 'PUT', 'PATCH', 'DELETE']) {
  R(m, '/api/ext/:id/*', ({ params, req, body, q }) => {
    const e = S.extensions.find((x) => x.id === params.id)
    if (!e || !e.has_api) fail(404, 'not_found', 'Unknown extension')
    if (!e.enabled) fail(409, 'disabled', 'Extension is disabled')
    if (e.error) fail(500, 'extension_error', e.error)
    if (e.id === 'notes' && params.rest === 'hello') return { hello: 'world', at: now() }
    if (e.id === 'notes') return { method: req.method, path: params.rest, query: Object.fromEntries(q), body }
    if (e.id === 'shop-sales' && params.rest === 'orders') return { orders: [{ id: 1042, total: 89, currency: 'EUR' }, { id: 1041, total: 34.5, currency: 'EUR' }] }
    fail(404, 'not_found', 'Unknown extension route')
  })
}

/* =================================================================== http plumbing */
function cookieToken(req) {
  const m = /(?:^|;\s*)mx_session=([^;]+)/.exec(req.headers.cookie || '')
  return m ? m[1] : null
}
function newToken() { const tk = crypto.randomBytes(24).toString('hex'); S.tokens.add(tk); return tk }
function setCookie(res, tk) { res.setHeader('Set-Cookie', `mx_session=${tk}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000`) }
const isAuthed = (req) => !S.setup_required && (S.autoAuth || S.tokens.has(cookieToken(req)))

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = []; let n = 0
    req.on('data', (c) => { n += c.length; if (n > 200 * 1024 * 1024) { reject(new HttpError(413, 'too_large', 'Body too large')); req.destroy() } else chunks.push(c) })
    req.on('end', () => resolve(Buffer.concat(chunks)))
    req.on('error', reject)
  })
}
function parseMultipart(buf, ctype) {
  const m = ctype.match(/boundary=(?:"([^"]+)"|([^;]+))/)
  if (!m || !buf.length) return []
  const b = Buffer.from('--' + (m[1] || m[2]))
  const files = []
  let pos = buf.indexOf(b)
  while (pos !== -1) {
    const start = pos + b.length
    if (buf.subarray(start, start + 2).toString() === '--') break
    const hEnd = buf.indexOf('\r\n\r\n', start)
    if (hEnd === -1) break
    const headers = buf.subarray(start + 2, hEnd).toString()
    const next = buf.indexOf(b, hEnd + 4)
    if (next === -1) break
    const data = buf.subarray(hEnd + 4, next - 2)
    const fn = headers.match(/filename="([^"]*)"/)
    const ct = headers.match(/content-type:\s*([^\r\n]+)/i)
    if (fn && fn[1]) files.push({ name: path.basename(fn[1]).replace(/[^\w.\- ]/g, '_'), data: Buffer.from(data), mime: ct ? ct[1].trim() : mimeOf(fn[1]) })
    pos = next
  }
  return files
}
function sendJson(res, status, obj) {
  if (res.headersSent) return
  const body = JSON.stringify(obj)
  res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'Content-Length': Buffer.byteLength(body) })
  res.end(body)
}

async function handleApi(req, res, url) {
  const p = url.pathname
  const candidates = routes.filter((r) => r.re.test(p))
  if (!candidates.length) return sendJson(res, 404, { error: 'not_found', message: `No route for ${p}` })
  const route = candidates.find((r) => r.method === req.method)
  if (!route) return sendJson(res, 405, { error: 'method_not_allowed', message: `${req.method} not allowed on ${p}` })
  if (req.method !== 'GET' && req.headers['x-maxxing'] !== '1') return sendJson(res, 403, { error: 'csrf', message: 'Missing X-Maxxing header' })
  const authed = isAuthed(req)
  if (!route.public && !authed) return sendJson(res, 401, { error: 'auth_required', message: 'Please log in' })
  const m = route.re.exec(p)
  const params = {}
  route.keys.forEach((k, i) => { params[k] = decodeURIComponent(m[i + 1]) })
  let rawBody = Buffer.alloc(0), body = {}
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    rawBody = await readBody(req)
    const ct = req.headers['content-type'] || ''
    if (rawBody.length && !ct.startsWith('multipart/')) {
      try { body = JSON.parse(rawBody.toString('utf8')) } catch { return sendJson(res, 400, { error: 'bad_json', message: 'Request body is not valid JSON' }) }
      if (body === null || typeof body !== 'object') body = {}
    }
  }
  const out = await route.handler({ req, res, q: url.searchParams, params, body, rawBody, authed })
  if (out === RAW) return
  sendJson(res, 200, out)
}

function serveStatic(req, res, url) {
  if (!fs.existsSync(path.join(DIST, 'index.html'))) {
    res.writeHead(503, { 'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store' })
    return res.end(`web/dist is missing (${DIST}). Run "npm run build" in web/ — or use "npm run dev" with MAXXING_API=http://127.0.0.1:${PORT}.\n`)
  }
  let rel
  try { rel = decodeURIComponent(url.pathname) } catch { rel = '/' }
  const file = path.resolve(DIST, '.' + path.posix.normalize(rel))
  if (file.startsWith(DIST + path.sep) && fs.existsSync(file) && fs.statSync(file).isFile()) {
    const immutable = rel.startsWith('/assets/')
    res.writeHead(200, { 'Content-Type': mimeOf(file) + (isText(mimeOf(file)) ? '; charset=utf-8' : ''), 'Cache-Control': immutable ? 'public, max-age=31536000, immutable' : 'no-cache' })
    return fs.createReadStream(file).pipe(res)
  }
  if (rel.startsWith('/assets/')) { res.writeHead(404, { 'Content-Type': 'text/plain' }); return res.end('Not found') }
  res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' })
  fs.createReadStream(path.join(DIST, 'index.html')).pipe(res)
}

function serveExt(req, res, url) {
  const m = /^\/ext\/([^/]+)\/page\.js$/.exec(url.pathname)
  if (!isAuthed(req)) return sendJson(res, 401, { error: 'auth_required', message: 'Please log in' })
  const e = m && S.extensions.find((x) => x.id === m[1] && x.type === 'page')
  if (!e) return sendJson(res, 404, { error: 'not_found', message: 'Unknown extension page' })
  if (!e.enabled) return sendJson(res, 409, { error: 'disabled', message: 'Extension is disabled' })
  const n = S.fs.get(`${ROOT}/extensions/${e.id}/page.js`)
  res.writeHead(200, { 'Content-Type': 'text/javascript; charset=utf-8', 'Cache-Control': 'no-store' })
  res.end(n ? n.content : NOTES_PAGE_JS)
}

function resetScenario(name) {
  for (const id of Object.keys(S?.timers || {})) for (const h of S.timers[id]) clearTimeout(h)
  GEN++
  S = buildState(name)
  startMaxxing()
  for (const set of sessionSubs.values()) for (const r of set) r.end()
  sessionSubs.clear()
  bus('sessions', 'workspace', 'tasks', 'crons', 'telegram', 'backup', 'health', 'extensions')
}

const server = http.createServer(async (req, res) => {
  const t0 = process.hrtime.bigint()
  let url
  try { url = new URL(req.url, 'http://localhost') } catch { res.writeHead(400); return res.end() }
  res.on('close', () => {
    const ms = Number(process.hrtime.bigint() - t0) / 1e6
    console.log(`${req.method} ${url.pathname}${url.search} ${res.statusCode} ${ms.toFixed(0)}ms`)
  })
  try {
    if (url.pathname === '/__mock/scenario') {
      if (req.method === 'GET') return sendJson(res, 200, { name: S.scenario, scenarios: SCENARIOS })
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method_not_allowed', message: 'Use POST' })
      let name
      try { name = JSON.parse((await readBody(req)).toString() || '{}').name } catch { name = null }
      if (!SCENARIOS.includes(name)) return sendJson(res, 422, { error: 'invalid', message: `name must be one of ${SCENARIOS.join(', ')}` })
      resetScenario(name)
      return sendJson(res, 200, { ok: true, name })
    }
    if (url.pathname === '/__mock/bus' && req.method === 'POST') { // emit a bus event, e.g. {"topics":["sessions","workspace"]}
      let topics
      try { topics = JSON.parse((await readBody(req)).toString() || '{}').topics } catch { topics = null }
      if (!Array.isArray(topics) || !topics.length) return sendJson(res, 422, { error: 'invalid', message: 'topics must be a non-empty list' })
      bus(...topics)
      return sendJson(res, 200, { ok: true })
    }
    if (url.pathname.startsWith('/api/') || url.pathname === '/api') return await handleApi(req, res, url)
    if (url.pathname.startsWith('/ext/')) return serveExt(req, res, url)
    if (req.method !== 'GET' && req.method !== 'HEAD') return sendJson(res, 405, { error: 'method_not_allowed', message: 'Static files are read-only' })
    return serveStatic(req, res, url)
  } catch (e) {
    if (e instanceof HttpError) return sendJson(res, e.status, { error: e.error, message: e.message })
    console.error(e)
    return sendJson(res, 500, { error: 'internal', message: String(e && e.message || e) })
  }
})

const initial = SCENARIOS.includes(process.env.MOCK_SCENARIO) ? process.env.MOCK_SCENARIO : 'ready'
S = buildState(initial)
startMaxxing()
server.listen(PORT, HOST, () => {
  console.log(`[mock] Harness Maxxing mock API on http://${HOST}:${PORT} — scenario "${initial}"${initial === 'setup' ? ` (setup token "${SETUP_TOKEN}")` : initial === 'login' ? ` (password "${DEFAULT_PASSWORD}")` : ''}`)
  console.log(`[mock] SPA from ${DIST}${fs.existsSync(DIST) ? '' : ' (missing — 503 until built)'} · switch: POST /__mock/scenario {"name":"setup|login|onboarding|ready|maxxing"}`)
})
