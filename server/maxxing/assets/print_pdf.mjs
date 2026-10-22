// node print_pdf.mjs <browser> <url> <out.pdf> - prints a page to PDF through the DevTools protocol
// (the headless shell has no --print-to-pdf). Node >= 22 (global WebSocket), no dependency.
import { spawn } from 'node:child_process'
import { writeFileSync } from 'node:fs'

const [browser, url, out] = process.argv.slice(2)
const proc = spawn(browser, ['--headless', '--no-sandbox', '--disable-gpu', '--remote-debugging-port=0', 'about:blank'],
  { stdio: ['ignore', 'ignore', 'pipe'] })
const fail = (msg) => { console.error(msg); proc.kill('SIGKILL'); process.exit(1) }
setTimeout(() => fail('timed out'), 120000).unref()

const wsUrl = await new Promise((resolve) => {
  let buf = ''
  proc.stderr.on('data', (d) => {
    buf += d
    const m = buf.match(/DevTools listening on (ws:\/\/\S+)/)
    if (m) resolve(m[1])
  })
  proc.on('exit', () => fail('browser exited: ' + buf.slice(-400)))
})
const ws = new WebSocket(wsUrl)
await new Promise((r) => ws.addEventListener('open', r, { once: true }))
let id = 0
const pending = new Map()
const waiters = []
ws.addEventListener('message', (e) => {
  const msg = JSON.parse(e.data)
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id)
    pending.delete(msg.id)
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result)
  } else if (msg.method) for (const w of waiters.filter((w) => w.method === msg.method)) w.resolve(msg.params)
})
const send = (method, params = {}, sessionId) =>
  new Promise((resolve, reject) => {
    pending.set(++id, { resolve, reject })
    ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }))
  })
const once = (method) => new Promise((resolve) => waiters.push({ method, resolve }))

const { targetId } = await send('Target.createTarget', { url: 'about:blank' })
const { sessionId } = await send('Target.attachToTarget', { targetId, flatten: true })
await send('Page.enable', {}, sessionId)
const loaded = once('Page.loadEventFired')
await send('Page.navigate', { url }, sessionId)
await loaded
await new Promise((r) => setTimeout(r, 500))              // web fonts, late layout
const { data } = await send('Page.printToPDF', { printBackground: true, preferCSSPageSize: true }, sessionId)
writeFileSync(out, Buffer.from(data, 'base64'))
ws.close()
proc.kill()
process.exit(0)
