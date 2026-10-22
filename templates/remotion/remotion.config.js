// Harness Maxxing: render with the server's one Chromium (Playwright's build in <state>/tools/browsers, shared with
// Scrapling and PDFs) instead of downloading a second browser. node_modules links to <state>/tools/remotion.
import { Config } from '@remotion/cli/config'
import { existsSync, readdirSync, realpathSync } from 'node:fs'
import { dirname, join } from 'node:path'

const findChromium = () => {
  try {
    const tools = dirname(dirname(realpathSync(join(process.cwd(), 'node_modules'))))
    for (const base of [join(tools, 'browsers'), '/var/lib/claude-maxxing/tools/browsers']) {
      if (!existsSync(base)) continue
      for (const d of readdirSync(base).filter((n) => n.startsWith('chromium-')).sort().reverse()) {
        for (const sub of ['chrome-linux64', 'chrome-linux']) {
          const exe = join(base, d, sub, 'chrome')
          if (existsSync(exe)) return exe
        }
      }
    }
  } catch {}
  return null
}

const chromium = process.env.REMOTION_BROWSER_EXECUTABLE || findChromium()
if (chromium) {
  Config.setBrowserExecutable(chromium)
  Config.setChromeMode('chrome-for-testing')
}
