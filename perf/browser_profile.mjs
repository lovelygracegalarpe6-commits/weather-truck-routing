// Where does main-thread time go during heatmap playback? CPU-profiles the page and
// attributes self time to the app bundle, the map library, and the browser itself.
//
//   node perf/browser_profile.mjs [app-url] [--seconds=6] [--size=1440x900]
import { chromium } from 'playwright-core'

const args = process.argv.slice(2)
const url = args.find((a) => a.startsWith('http')) ?? 'http://127.0.0.1:8001/'
const seconds = Number(args.find((a) => a.startsWith('--seconds='))?.split('=')[1] ?? 6)
const [width, height] = (args.find((a) => a.startsWith('--size='))?.split('=')[1] ?? '1440x900').split('x').map(Number)
const chrome = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'

const browser = await chromium.launch({ executablePath: chrome, headless: true, args: ['--ignore-gpu-blocklist', '--no-proxy-server'] })
const page = await browser.newPage({ viewport: { width, height } })
// Load twice so basemap tiles and fonts come from the HTTP cache, then let the map
// settle: profiling while tiles are still arriving measures a half-drawn map (and looked
// ~2x faster than steady state when this script first ran).
for (let i = 0; i < 2; i++) {
  await page.goto(url, { waitUntil: 'load' })
  await page.getByRole('button', { name: 'Chicago → Nashville' }).click()
  await page.waitForFunction(() => document.querySelector('.timeline') && !document.querySelector('.timeline-status'), null, { timeout: 180_000 })
}
await page.waitForTimeout(5000)

// Guard: a hidden or collapsed map renders nothing and makes every frame look cheap.
const mapSize = await page.evaluate(() => {
  const r = document.querySelector('.maplibregl-canvas')?.getBoundingClientRect()
  return r ? [Math.round(r.width), Math.round(r.height)] : null
})
if (!mapSize || mapSize[0] < 300 || mapSize[1] < 300) {
  throw new Error(`Map canvas is not visible (${mapSize}); refusing to report frame timings`)
}

const cdp = await page.context().newCDPSession(page)
await cdp.send('Profiler.enable')
await cdp.send('Profiler.setSamplingInterval', { interval: 500 })
await page.getByRole('button', { name: 'Play forecast animation' }).click()
await cdp.send('Profiler.start')
const frames = await page.evaluate(
  (ms) => new Promise((resolve) => {
    let n = 0
    const start = performance.now()
    const tick = (t) => (++n, t - start < ms ? requestAnimationFrame(tick) : resolve(n))
    requestAnimationFrame(tick)
  }),
  seconds * 1000,
)
const { profile } = await cdp.send('Profiler.stop')
await browser.close()

const nodes = new Map(profile.nodes.map((n) => [n.id, n]))
const self = new Map()
profile.samples.forEach((id, i) => self.set(id, (self.get(id) ?? 0) + (profile.timeDeltas[i] ?? 0)))
const byBucket = new Map()
const byFunction = new Map()
for (const [id, us] of self) {
  const { functionName, url: src, lineNumber } = nodes.get(id).callFrame
  const file = src.split('/').pop().split('?')[0]
  const bucket = !src
    ? functionName.startsWith('(') ? functionName : 'native/browser'
    : file.includes('maplibre-gl-worker') ? 'map worker' : /^index-.*\.js$/.test(file) ? 'app chunk (React + our code)' : /^MapView-.*\.js$/.test(file) ? 'map chunk (MapLibre + MapView)' : file
  byBucket.set(bucket, (byBucket.get(bucket) ?? 0) + us)
  const key = `${functionName || '(anonymous)'}  ${file}:${lineNumber}:${nodes.get(id).callFrame.columnNumber}`
  byFunction.set(key, (byFunction.get(key) ?? 0) + us)
}
const total = [...self.values()].reduce((a, b) => a + b, 0)
console.log(`${width}x${height}: ${(frames / seconds).toFixed(1)} fps over ${seconds}s\n`)
for (const [k, us] of [...byBucket].sort((a, b) => b[1] - a[1])) console.log(`${((us / total) * 100).toFixed(1).padStart(5)}%  ${k}`)
console.log('\nTop functions (self time):')
for (const [k, us] of [...byFunction].sort((a, b) => b[1] - a[1]).slice(0, 15)) {
  console.log(`${((us / total) * 100).toFixed(1).padStart(5)}%  ${k}`)
}
