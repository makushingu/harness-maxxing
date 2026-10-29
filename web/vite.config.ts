import { defineConfig, loadEnv, transformWithOxc } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'
import fs from 'node:fs'
import crypto from 'node:crypto'
import zlib from 'node:zlib'
import type { Plugin } from 'vite'
import { GROUPS } from './src/i18n/groups'

/** Emits dist/sw.js from sw/sw.js with this build's version (hash of every output file name) and the app-shell
 *  precache list (entry chunk + its static imports + CSS). A new build ⇒ a new sw.js ⇒ the update toast. */
function serviceWorker(): Plugin {
  return {
    name: 'maxxing-sw',
    apply: 'build',
    generateBundle(_opts, bundle) {
      const files = Object.keys(bundle).sort()
      const version = crypto.createHash('sha256').update(files.join('\n')).digest('hex').slice(0, 12)
      const shell = new Set<string>()
      const visit = (name: string) => {
        const c = bundle[name]
        if (!c || shell.has(name)) return
        shell.add(name)
        if (c.type === 'chunk') {
          c.imports.forEach(visit)
          c.viteMetadata?.importedCss.forEach((css) => shell.add(css))
        }
      }
      for (const [name, c] of Object.entries(bundle)) if (c.type === 'chunk' && c.isEntry) visit(name)
      // The default font (Inter, Latin) is part of the shell too. The other fonts (Settings > Appearance, loaded on
      // demand) are cached by the service worker the first time they are used, like lazy chunks.
      for (const name of files) if (/^assets\/inter-latin-wght-normal.*\.woff2$/.test(name)) shell.add(name)
      const precache = [...shell].filter((f) => f.startsWith('assets/')).map((f) => '/' + f)
      const src = fs.readFileSync(path.resolve(import.meta.dirname, 'sw/sw.js'), 'utf8')
      this.emitFile({
        type: 'asset',
        fileName: 'sw.js',
        source: src
          .replace("const VERSION = '__MX_VERSION__'", `const VERSION = ${JSON.stringify(version)}`)
          .replace('const PRECACHE = __MX_PRECACHE__', `const PRECACHE = ${JSON.stringify(precache)}`),
      })
    },
  }
}

/** Writes a Brotli twin (`<file>.br`, quality 11) next to every JS/CSS asset; the server sends it to browsers that
 *  accept `br` (~18 % smaller than the proxy's on-the-fly gzip). Also preloads the Latin Inter font, which the CSS
 *  would otherwise only discover after it is downloaded and parsed. */
function precompress(): Plugin {
  let outDir = 'dist'
  return {
    name: 'maxxing-precompress',
    apply: 'build',
    configResolved(c) {
      outDir = path.resolve(c.root, c.build.outDir)
    },
    transformIndexHtml: {
      order: 'post',
      handler(_html, ctx) {
        const font = Object.keys(ctx.bundle || {}).find((f) => /inter-latin-wght-normal.*\.woff2$/.test(f))
        return font ? [{ tag: 'link', attrs: { rel: 'preload', href: '/' + font, as: 'font', type: 'font/woff2', crossorigin: '' }, injectTo: 'head' }] : []
      },
    },
    writeBundle(_opts, bundle) {
      for (const name of Object.keys(bundle)) {
        if (!/^assets\/.+\.(js|css)$/.test(name)) continue
        const file = path.join(outDir, name)
        const src = fs.readFileSync(file)
        if (src.length < 1024) continue
        fs.writeFileSync(file + '.br', zlib.brotliCompressSync(src, { params: { [zlib.constants.BROTLI_PARAM_QUALITY]: 11, [zlib.constants.BROTLI_PARAM_SIZE_HINT]: src.length } }))
      }
    },
  }
}

/** Splits each dictionary (src/i18n/<lang>.ts) into chunks: `virtual:i18n/<lang>/<part>` is the core (every
 *  namespace not in src/i18n/groups.ts) or one group; `virtual:i18n-loaders` maps language -> part -> import(). The
 *  dictionary files stay whole for TypeScript (fr.ts must have every key of en.ts) and for editing. */
function i18nSplit(): Plugin {
  const dir = path.resolve(import.meta.dirname, 'src/i18n')
  const langs = () => fs.readdirSync(dir).filter((f) => /^[a-z]{2}\.ts$/.test(f)).map((f) => f.slice(0, 2)).sort()
  const parts = ['core', ...Object.keys(GROUPS)]
  const groupOf = new Map<string, string>(Object.entries(GROUPS).flatMap(([g, names]) => names.map((n) => [n, g] as const)))
  const PREFIX = 'virtual:i18n/'
  return {
    name: 'maxxing-i18n-split',
    resolveId(id) {
      if (id === 'virtual:i18n-loaders') return '\0i18n-loaders'
      if (id.startsWith(PREFIX)) return '\0i18n-' + id.slice(PREFIX.length).replace('/', '-') + '.js'
    },
    async load(id) {
      if (id === '\0i18n-loaders') {
        const lines = langs().map((l) => `  ${l}: {\n${parts.map((p) => `    ${p}: () => import('${PREFIX}${l}/${p}'),`).join('\n')}\n  },`)
        return `export const loaders = {\n${lines.join('\n')}\n}\n`
      }
      const m = /^\0i18n-([a-z]{2})-([a-z]+)\.js$/.exec(id)
      if (!m) return
      const file = path.join(dir, `${m[1]}.ts`)
      this.addWatchFile(file)
      const js = (await transformWithOxc(fs.readFileSync(file, 'utf8'), file, { lang: 'ts' })).code
      const mod = await import('data:text/javascript;base64,' + Buffer.from(js).toString('base64'))
      const dict = Object.values(mod)[0] as Record<string, string>
      const keep = Object.entries(dict).filter(([k]) => (groupOf.get(k.split('.', 1)[0]) ?? 'core') === m[2])
      return `export default ${JSON.stringify(Object.fromEntries(keep))}\n`
    },
  }
}

/** Preloads, from index.html, the lazy chunks the first render will need: the page chunk of the URL being opened
 *  (+ its static imports) and the dictionary chunks of the UI language (core + the route's groups). Without this they are only requested once the
 *  entry chunk has been downloaded and run (one more round trip before the first useful paint). The route table
 *  is read from src/routes.tsx (`path: '…', lazy: page(() => import('./pages/…'), ['group', …])`). */
function routePreload(): Plugin {
  let root = ''
  return {
    name: 'maxxing-route-preload',
    apply: 'build',
    configResolved(c) {
      root = c.root
    },
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        const bundle = ctx.bundle
        if (!bundle) return html
        const chunks = Object.values(bundle).filter((c) => c.type === 'chunk')
        const entryGraph = new Set<string>()
        const walk = (name: string, into: Set<string>) => {
          const c = bundle[name]
          if (!c || c.type !== 'chunk' || into.has(name)) return
          into.add(name)
          c.imports.forEach((n) => walk(n, into))
        }
        for (const c of chunks) if (c.isEntry) walk(c.fileName, entryGraph)
        const filesOf = (srcNoExt: string) => {
          const c = chunks.find((x) => x.facadeModuleId && x.isDynamicEntry && x.facadeModuleId.replace(/\.(tsx?|jsx?)$/, '').replace(/\/index$/, '') === srcNoExt)
          if (!c) return null
          const set = new Set<string>()
          walk(c.fileName, set)
          return [...set].filter((f) => !entryGraph.has(f)).map((f) => '/' + f)
        }
        const src = fs.readFileSync(path.join(root, 'src/routes.tsx'), 'utf8')
        const routes: [string, string[], string[]][] = []
        for (const m of src.matchAll(/\{\s*(?:index: true|path: '([^']*)')\s*,\s*lazy: page\(\(\) => import\('\.\/([^']+)'\)(?:, \[([^\]]*)\])?\)/g)) {
          const files = filesOf(path.join(root, 'src', m[2]).replace(/\/index$/, ''))
          if (!files) continue
          const re = m[1] === undefined ? '' : m[1].replace(/:[^/]+/g, '[^/]+').replace(/\/\*$/, '(/.*)?')
          routes.push([`^/${re}$`, files, [...(m[3] ?? '').matchAll(/'([a-z]+)'/g)].map((g) => g[1])])
        }
        // Dictionary chunks (i18nSplit): language -> part (core or group) -> file.
        const langs: Record<string, Record<string, string>> = {}
        for (const c of chunks) {
          const m = c.facadeModuleId && /^\0i18n-([a-z]{2})-([a-z]+)\.js$/.exec(c.facadeModuleId)
          if (m && c.isDynamicEntry) (langs[m[1]] ??= {})[m[2]] = '/' + c.fileName
        }
        // Language: same rule as src/stores/ui.ts (stored choice, else the browser's).
        const code = `(function(){try{var m=${JSON.stringify({ r: routes, l: langs })},p=location.pathname,l=[],G=['core'],i;
for(i=0;i<m.r.length;i++)if(new RegExp(m.r[i][0]).test(p)){l=m.r[i][1];G=G.concat(m.r[i][2]);break}
var s=JSON.parse(localStorage.getItem('mx-ui')||'{}').state||{},g=s.language||((navigator.language||'').toLowerCase().indexOf('fr')===0?'fr':'en');
var d=m.l[g]||{};for(i=0;i<G.length;i++)if(d[G[i]])l.push(d[G[i]]);for(i=0;i<l.length;i++){var k=document.createElement('link');k.rel='modulepreload';k.crossOrigin='';k.fetchPriority='low';k.href=l[i];document.head.appendChild(k)}}catch(e){}})()`
        // Right after the boot script, before the stylesheet: an inline script placed after a stylesheet waits for it.
        const at = html.indexOf('</script>') + '</script>'.length
        return html.slice(0, at) + `\n    <script>${code}</script>` + html.slice(at)
      },
    },
  }
}

// Dev: `npm run dev` proxies /api and /ext to the backend.
// Override the target with MAXXING_API=http://127.0.0.1:8809 (mock) in the env or web/.env.local.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = env.MAXXING_API || 'http://127.0.0.1:8801'
  return {
    plugins: [i18nSplit(), react(), tailwindcss(), serviceWorker(), precompress(), routePreload()],
    resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
    server: {
      port: 5173,
      proxy: {
        '/api': { target, changeOrigin: false, ws: false },
        '/ext': { target, changeOrigin: false },
      },
    },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      emptyOutDir: true,
      chunkSizeWarningLimit: 900,
      sourcemap: false,
      // Stable vendor chunks: a release that only touches app code keeps these in the browser/service-worker
      // cache (their hashes do not change), and they download in parallel with the entry chunk.
      rolldownOptions: {
        // The design system files only define components: a barrel import (`@/components/ui`) keeps the ones it uses,
        // not all of them (and their Radix libraries) in the first load.
        treeshake: { moduleSideEffects: (id: string) => !/[\\/]src[\\/]components[\\/]ui[\\/][^\\/]+\.tsx?$/.test(id) },
        output: {
          advancedChunks: {
            groups: [
              { name: 'vendor-react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 30 },
              { name: 'vendor-router', test: /node_modules[\\/](react-router|@remix-run|cookie|set-cookie-parser)[\\/]/, priority: 25 },
              { name: 'vendor-query', test: /node_modules[\\/]@tanstack[\\/]/, priority: 25 },
              // The Radix parts no eager screen uses (selects, checkboxes, tabs, scroll areas, avatars...) stay out:
              // they load with the lazy pages that use them instead of riding in vendor-ui on every first load.
              {
                name: 'vendor-ui',
                test: /node_modules[\\/](@radix-ui[\\/](?!react-(select|checkbox|tabs|scroll-area|avatar|separator|label)[\\/]|number[\\/])|@floating-ui|sonner|react-remove-scroll|aria-hidden|class-variance-authority|tailwind-merge|clsx)/,
                priority: 20,
              },
            ],
          },
        },
      },
    },
  }
})
