// Plain-language titles of tool calls in a thread ("Runs the tests", "Searches “useT”", "Reads Items.tsx") instead of
// the tool's name and its raw input. A Bash call has its own sentence (`description`, written by Claude in the
// language of the session); without one, the first command of the line is recognised (`bashAction`). What the call
// really runs stays on screen next to it (the command, the path, the pattern) and in full when the card opens.
import type { TKey, TFn } from '@/i18n'

type T = TFn
type Input = Record<string, unknown>

/** What a call does, for the grouping of read-only calls ("Explored 4 files · 2 searches"). */
type ToolKind = 'read' | 'search' | 'list' | 'look' | 'other'

type ToolLabel = {
  /** The sentence shown in front ("Runs the tests"). */
  title: string
  /** What it runs, shown after it in monospace (command, path, pattern…); '' = nothing more. */
  detail: string
  kind: ToolKind
  /** A command that deletes or rewrites things for good: its command always shows, with a badge. */
  danger: boolean
}

const str = (v: unknown) => (typeof v === 'string' ? v : '')
const one = (s: string, max = 160) => {
  const l = s.replace(/\s+/g, ' ').trim()
  return l.length > max ? `${l.slice(0, max - 1)}…` : l
}

/** Commands that delete or rewrite for good, whatever the sentence in front says. */
const DANGER =
  /(^|[;&|(]\s*|\s)(rm\s+-[a-z]*[rf]|rm\s|rmdir\s|shred\s|mkfs|dd\s+if=|truncate\s)|git\s+(reset\s+--hard|clean\s+-[a-z]*f|push\s+[^|;&]{0,200}(--force|-f\b)|branch\s+-D|checkout\s+--\s|restore\s)|\b(drop|truncate)\s+(table|database|schema)\b|\bdelete\s+from\b|>\s*\/dev\/sd/i

function isDangerous(command: string): boolean {
  return DANGER.test(command)
}

/** Longer commands are parsed on their start only (a here-document, a pasted script): bounded work per card. */
const PARSE_MAX = 4000

/** The command a Bash line is about: `cd x && env A=1 sudo timeout 5 grep …` -> ["grep", "…"]. */
function mainCommand(command: string): string[] {
  // redirections and here-documents are not arguments (`cat a 2>/dev/null`, `python3 - <<EOF`)
  const line = command.slice(0, PARSE_MAX).split('\n', 1)[0].replace(/\d*>&\d/g, '').replace(/\d*>>?\s*\S+/g, '').replace(/<<-?\s*['"]?\w+['"]?/g, '-').replace(/<\s*\S+/g, '')
  const parts = line.split(/&&|\|\||;|\|/) // no \s* around: quadratic on a long run of spaces
  for (const part of parts) {
    // control words and subshells around the real command (`for f in …; do convert …`, `(cd x; ls)`)
    const words = part.trim().replace(/^[({]+\s*/, '').replace(/^(do|then|else)\s+/, '').split(/\s+/).filter(Boolean)
    if (/^(for|if|elif|fi|done|esac|case|[)}]+)$/.test(words[0] || '')) continue
    // prefixes that do not say what the line does
    while (words.length) {
      const w = words[0]
      if (/^[A-Za-z_][A-Za-z0-9_]*=\$\(/.test(w)) words.length = 0
      else if (/^[A-Za-z_][A-Za-z0-9_]*=/.test(w) || w === 'sudo' || w === 'nice' || w === 'nohup' || w === 'exec' || w === 'time' || w === 'command') words.shift()
      else if (w === 'env') {
        words.shift()
        while (words.length && (words[0].startsWith('-') || /^[A-Za-z_][A-Za-z0-9_]*=/.test(words[0]))) if (words.shift() === '-u') words.shift()
      } else if (w === 'timeout') {
        words.shift()
        while (words.length && (words[0].startsWith('-') || /^\d/.test(words[0]))) words.shift()
      } else break
    }
    if (words[0] === 'cd' && parts.length === 1) return words
    if (!words.length || words[0] === 'cd' || words[0] === 'set' || words[0] === 'export' || words[0] === 'source' || words[0] === '.') continue
    return words
  }
  return []
}

const base = (p: string) => p.replace(/\/+$/, '').split('/').pop() || p
const unquote = (s: string) => s.replace(/^(['"])(.*)\1$/, '$2')
/** First argument that is not an option (`grep -rn "x" src` -> "x"). */
const firstArg = (args: string[]) => {
  for (let i = 0; i < args.length; i++) {
    const a = args[i]
    if (a === '-e' || a === '--regexp') return unquote(args[i + 1] || '')
    if (!a.startsWith('-')) return unquote(a)
  }
  return ''
}

/** A Bash line without a sentence -> [i18n key, its values, kind], or null (the raw command is shown). */
function bashAction(command: string): [string, Record<string, string>, ToolKind] | null {
  const w = mainCommand(command)
  if (!w.length) return null
  const cmd = base(w[0])
  const args = w.slice(1)
  const sub = args.find((a) => !a.startsWith('-')) || ''
  const line = w.join(' ')
  if ((cmd === 'until' || cmd === 'while') && /\bsleep\b/.test(command)) return ['tl.bash.wait', {}, 'other']
  if (cmd === 'cd') return ['tl.bash.cd', {}, 'list']
  if (w[0].startsWith('./') || w[0].startsWith('../') || (w[0].startsWith('/') && /\.(py|sh|js|mjs|ts)$/.test(w[0]))) return ['tl.bash.script', { name: cmd }, 'other']
  if (/\b(pytest|vitest|jest|playwright test)\b/.test(line) || /^(npm|pnpm|yarn|bun) (run )?test\b/.test(line) || /^(go|cargo) test\b/.test(line)) return ['tl.bash.test', {}, 'other']
  switch (cmd) {
    case 'grep':
    case 'egrep':
    case 'rg':
    case 'ag':
    case 'ack': {
      const pat = firstArg(args)
      return pat ? ['tl.bash.search', { what: one(pat, 60) }, 'search'] : ['tl.bash.searchAny', {}, 'search']
    }
    case 'find':
    case 'fd':
    case 'locate':
      return ['tl.bash.find', {}, 'search']
    case 'ls':
    case 'tree':
    case 'du':
    case 'df':
      return ['tl.bash.list', {}, 'list']
    case 'cat':
    case 'head':
    case 'tail':
    case 'less':
    case 'bat':
    case 'wc':
    case 'cut':
    case 'sort':
    case 'uniq':
    case 'diff':
    case 'cmp':
    case 'md5sum':
    case 'sha256sum':
    case 'xxd':
    case 'od':
    case 'strings':
    case 'jq':
    case 'stat':
    case 'file': {
      const f = args.filter((a) => !a.startsWith('-') && !/^\d+$/.test(a)).pop()
      return f ? ['tl.bash.read', { file: base(unquote(f)) }, 'read'] : ['tl.bash.readAny', {}, 'read']
    }
    case 'sed':
      return args.includes('-i') || args.some((a) => /^-[a-z]*i/.test(a)) ? ['tl.bash.edit', {}, 'other'] : ['tl.bash.readAny', {}, 'read']
    case 'git': {
      const known = ['status', 'log', 'diff', 'show', 'commit', 'push', 'pull', 'fetch', 'checkout', 'switch', 'branch', 'merge', 'rebase', 'worktree', 'clone', 'add', 'stash', 'tag', 'blame', 'reset', 'cherry-pick', 'revert']
      const s = args.find((a, i) => !a.startsWith('-') && !(i > 0 && args[i - 1] === '-C') && !(i > 0 && args[i - 1] === '-c')) || ''
      if (!known.includes(s)) return ['tl.bash.git', {}, 'other']
      const readOnly = ['status', 'log', 'diff', 'show', 'blame'].includes(s)
      return [`tl.bash.git.${s === 'switch' ? 'checkout' : s}`, {}, readOnly ? 'look' : 'other']
    }
    case 'npm':
    case 'pnpm':
    case 'yarn':
    case 'bun':
      if (sub === 'ci' || sub === 'install' || sub === 'i' || sub === 'add') return ['tl.bash.install', {}, 'other']
      if (args.includes('build')) return ['tl.bash.build', {}, 'other']
      if (args.includes('typecheck') || args.includes('lint')) return ['tl.bash.check', {}, 'other']
      return sub === 'run' || sub === 'exec' ? ['tl.bash.script', { name: args[args.indexOf(sub) + 1] || cmd }, 'other'] : null
    case 'npx':
      return args[0] === 'tsc' ? ['tl.bash.check', {}, 'other'] : ['tl.bash.script', { name: args[0] || cmd }, 'other']
    case 'tsc':
      return ['tl.bash.check', {}, 'other']
    case 'vite':
      return ['tl.bash.build', {}, 'other']
    case 'pip':
    case 'pip3':
    case 'apt':
    case 'apt-get':
      return sub === 'install' ? ['tl.bash.install', {}, 'other'] : null
    case 'uv':
      if (sub === 'sync' || sub === 'add' || sub === 'lock' || (sub === 'pip' && args.includes('install'))) return ['tl.bash.install', {}, 'other']
      if (sub === 'run') {
        const s = args[args.indexOf('run') + 1]
        return s ? ['tl.bash.script', { name: base(s) }, 'other'] : null
      }
      return null
    case 'python':
    case 'python3':
    case 'node':
    case 'bash':
    case 'sh': {
      if (args.includes('-c') || args.includes('-e') || args.includes('-')) return ['tl.bash.snippet', {}, 'other']
      const s = args.find((a) => !a.startsWith('-') && a !== 'm')
      return s ? ['tl.bash.script', { name: base(s) }, 'other'] : ['tl.bash.snippet', {}, 'other']
    }
    case 'curl':
    case 'wget':
    case 'http': {
      const url = args.find((a) => /^['"]?https?:\/\//.test(a))
      let host = ''
      try {
        host = url ? new URL(unquote(url)).host : ''
      } catch {
        /* not a URL */
      }
      return host ? ['tl.bash.http', { host }, 'other'] : ['tl.bash.httpAny', {}, 'other']
    }
    case 'systemctl':
      if (sub === 'status' || sub === 'is-active' || sub === 'list-units') return ['tl.bash.service', {}, 'look']
      return sub === 'restart' || sub === 'start' || sub === 'stop' || sub === 'reload' ? [`tl.bash.svc.${sub}`, { name: args[args.indexOf(sub) + 1] || '' }, 'other'] : null
    case 'journalctl':
      return ['tl.bash.logs', {}, 'look']
    case 'mkdir':
      return ['tl.bash.mkdir', {}, 'other']
    case 'cp':
    case 'rsync':
      return ['tl.bash.copy', {}, 'other']
    case 'mv':
      return ['tl.bash.move', {}, 'other']
    case 'rm':
    case 'rmdir':
      return ['tl.bash.delete', {}, 'other']
    case 'chmod':
    case 'chown':
      return ['tl.bash.perms', {}, 'other']
    case 'sleep':
      return ['tl.bash.wait', {}, 'other']
    case 'ps':
    case 'pgrep':
    case 'top':
    case 'free':
    case 'uptime':
      return ['tl.bash.procs', {}, 'look']
    case 'kill':
    case 'pkill':
    case 'killall':
      return ['tl.bash.kill', {}, 'other']
    case 'ffmpeg':
    case 'ffprobe':
      return ['tl.bash.media', {}, 'other']
    case 'magick':
    case 'convert':
    case 'identify':
    case 'rsvg-convert':
    case 'cwebp':
    case 'optipng':
    case 'exiftool':
      return ['tl.bash.image', {}, 'other']
    case 'scrapling':
    case 'scrapling-python':
      return ['tl.bash.scrape', {}, 'other']
    case 'wrangler':
    case 'vercel':
    case 'netlify':
      return sub === 'deploy' || sub === 'publish' ? ['tl.bash.deploy', {}, 'other'] : ['tl.bash.script', { name: cmd }, 'other']
    case 'gh':
      return ['tl.bash.github', {}, 'other']
    case 'ssh':
    case 'scp':
      return ['tl.bash.ssh', {}, 'other']
    case 'echo':
    case 'printf':
    case 'date':
    case 'which':
    case 'whoami':
    case 'pwd':
    case 'type':
      return ['tl.bash.check', {}, 'look']
    case 'tar':
    case 'zip':
    case 'unzip':
    case 'gzip':
      return ['tl.bash.archive', {}, 'other']
    case 'maxxing':
      return ['tl.bash.maxxing', { what: sub }, sub === 'status' || sub === 'doctor' || (sub && args.includes('list')) ? 'look' : 'other']
  }
  return null
}

/** The title and detail of a tool call. `rel` shortens a path for display (relative to the topic). */
export function toolLabel(name: string, input: Input, tr: T, rel: (path: string) => string): ToolLabel {
  const t = (key: string, vars?: Record<string, string | number>) => tr(key as TKey, vars)
  const g = (k: string) => str(input[k])
  const label = (title: string, detail = '', kind: ToolKind = 'other', danger = false): ToolLabel => ({ title: title || name, detail, kind, danger })
  const where = (p: string) => (p ? t('tl.in', { where: rel(p) }) : '')
  switch (name) {
    case 'Bash': {
      const cmd = one(g('command'), 400)
      const danger = isDangerous(g('command'))
      const action = bashAction(g('command'))
      const desc = one(g('description'), 120)
      if (desc) return label(desc, cmd, action?.[2] ?? 'other', danger)
      if (action) return label(t(action[0], action[1]), cmd, danger ? 'other' : action[2], danger)
      return label(t('tl.bash.run'), cmd, 'other', danger)
    }
    case 'BashOutput':
      return label(t('tl.bashOutput'))
    case 'KillShell':
    case 'KillBash':
      return label(t('tl.killShell'))
    case 'Read':
    case 'NotebookRead':
      return label(t('tl.read'), rel(g('file_path') || g('notebook_path')), 'read')
    case 'Write':
      return label(t('tl.write'), rel(g('file_path')))
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
      return label(t('tl.edit'), rel(g('file_path') || g('notebook_path')))
    case 'Grep':
      return label(t('tl.grep', { what: one(g('pattern'), 60) }), where(g('path')) || g('glob'), 'search')
    case 'Glob':
      return label(t('tl.glob'), `${g('pattern')}${g('path') ? ` ${where(g('path'))}` : ''}`, 'search')
    case 'LS':
      return label(t('tl.bash.list'), rel(g('path')), 'list')
    case 'WebFetch':
      return label(t('tl.webFetch'), g('url'))
    case 'WebSearch':
      return label(t('tl.webSearch'), g('query'))
    case 'Task':
    case 'Agent':
      return label(g('description') || t('tl.agent'), g('subagent_type'))
    case 'TodoWrite': {
      const n = Array.isArray(input.todos) ? input.todos.length : 0
      return label(t('tl.todos', { count: n }))
    }
    case 'Skill':
      return label(t('tl.skill'), g('skill') || g('name'))
    case 'ToolSearch':
      return label(t('tl.toolSearch'), g('query'))
  }
  return { title: '', detail: '', kind: 'other', danger: false } // the card keeps its name and summary
}

/** Options that make a read-only command write or run something (`find -delete`, `sort -o`, `rg --pre`, `git -c`). */
const UNSAFE_OPT = /^(-delete|-exec\S*|-ok\S*|-fprint\S*|-fls|--output\S*|--pre\S*)$/
const UNSAFE_BY_CMD: Record<string, RegExp> = {
  sort: /^-[a-zA-Z]*o/,
  fd: /^(-[a-zA-Z]*[xX]|--exec\S*)$/,
  xxd: /^-[a-zA-Z]*r/,
  tree: /^-[a-zA-Z]*o/,
  journalctl: /^--(vacuum|rotate|flush|sync|relinquish)\S*$/,
  date: /^(-[a-zA-Z]*s|--set\S*)$/,
  git: /^(-c|--config-env\S*|--exec-path\S*)$/, sed: /^(-[a-z]*i|--in-place)|[/;{}'"0-9][wW]['"]?$/ }

/** The kind of a call without its texts (grouping in the thread). A group is folded, so a Bash line joins one only
 *  when EVERY command in it only reads: no pipe into another program, no `$(…)`, no second line, no background job,
 *  no redirection into a file, no option that writes or runs something. Anything unsure is 'other' (shown alone). */
export function toolKind(name: string, input: Input): ToolKind {
  if (name === 'Read' || name === 'NotebookRead') return 'read'
  if (name === 'Grep' || name === 'Glob') return 'search'
  if (name === 'LS') return 'list'
  if (name !== 'Bash') return 'other'
  const cmd = str(input.command)
  if (cmd.length > PARSE_MAX || /[\n\r`]|\$\(|<\(|>\(/.test(cmd) || isDangerous(cmd)) return 'other'
  const plain = cmd.replace(/\d*>>?\s*\/dev\/null/g, '').replace(/\d*>&\d/g, '')
  if (/>|\btee\b/.test(plain) || /(^|[^&])&([^&]|$)/.test(plain)) return 'other' // writes a file, or runs in the background
  let kind: ToolKind | null = null
  for (const seg of plain.split(/&&|\|\||;|\|/)) {
    const words = seg.trim().split(/\s+/).filter(Boolean)
    if (!words.length) continue
    if (words[0] === 'cd' && words.length <= 2) continue
    const by = UNSAFE_BY_CMD[words[0].split('/').pop() || '']
    if (words.slice(1).some((w) => UNSAFE_OPT.test(w) || by?.test(w))) return 'other'
    if (words[0] === 'uniq' && words.slice(1).filter((w) => !w.startsWith('-')).length > 1) return 'other' // uniq IN OUT writes OUT
    const k = bashAction(seg)?.[2]
    if (!k || k === 'other') return 'other'
    kind ??= k
  }
  return kind ?? 'other'
}
