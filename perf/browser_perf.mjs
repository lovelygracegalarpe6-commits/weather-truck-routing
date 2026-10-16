// Frontend performance: load, plan-to-render, slider cost, playback smoothness, memory.
//
//   node perf/browser_perf.mjs [app-url] [--headed] [--cpu-throttle=4]
//
// Run against `python perf/serve.py` (production build + mock upstreams). Results are
// printed and saved to perf/results/browser.json.
import { mkdirSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium } from 'playwright-core'

const args = process.argv.slice(2)
const url = args.find((a) => a.startsWith('http')) ?? 'http://127.0.0.1:8001/'
const headed = args.includes('--headed')
const throttle = Number(args.find((a) => a.startsWith('--cpu-throttle='))?.split('=')[1] ?? 1)
const chrome = process.env.CHROME_PATH ?? 'C:/Program Files/Google/Chrome/Application/chrome.exe'

const pct = (values, p) => {
  const s = [...values].sort((a, b) => a - b)
  return s[Math.min(s.length - 1, Math.round((p / 100) * (s.length - 1)))]
}
const r1 = (x) => Math.round(x * 10) / 10

const browser = await chromium.launch({
  executablePath: chrome,
  headless: !headed,
  args: ['--ignore-gpu-blocklist', '--no-proxy-server', '--window-size=1440,900', ...(headed ? ['--window-position=-3000,-3000'] : [])],
})
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
const cdp = await context.newCDPSession(page)
await cdp.send('Performance.enable')
if (throttle > 1) await cdp.send('Emulation.setCPUThrottlingRate', { rate: throttle })

// Observers must exist before the page runs.
await page.addInitScript(() => {
  window.__perf = { longtasks: [], lcp: 0, cls: 0 }
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) window.__perf.longtasks.push({ start: e.startTime, duration: e.duration })
  }).observe({ type: 'longtask', buffered: true })
  new PerformanceObserver((list) => {
    window.__perf.lcp = list.getEntries().at(-1).startTime
  }).observe({ type: 'largest-contentful-paint', buffered: true })
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) if (!e.hadRecentInput) window.__perf.cls += e.value
  }).observe({ type: 'layout-shift', buffered: true })
})

const longTasksSince = (t) =>
  page.evaluate((t) => window.__perf.longtasks.filter((l) => l.start >= t), t)
const now = () => page.evaluate(() => performance.now())
const scriptSeconds = async () => {
  const { metrics } = await cdp.send('Performance.getMetrics')
  const get = (name) => metrics.find((m) => m.name === name)?.value ?? 0
  return { script: get('ScriptDuration'), task: get('TaskDuration') }
}

const results = { url, headed, cpuThrottle: throttle }

// 1. Load -------------------------------------------------------------------------------
// Median of 5 cold loads, each in a fresh context (empty cache), for stable paint timings.
const coldLoads = []
for (let i = 0; i < 5; i++) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
  const p = await ctx.newPage()
  await p.goto(url, { waitUntil: 'load' })
  await p.waitForTimeout(1200)
  coldLoads.push(
    await p.evaluate(() => {
      const nav = performance.getEntriesByType('navigation')[0]
      return {
        ttfb: nav.responseStart,
        dcl: nav.domContentLoadedEventEnd,
        fcp: performance.getEntriesByName('first-contentful-paint')[0]?.startTime ?? NaN,
      }
    }),
  )
  await ctx.close()
}
const median = (key) => pct(coldLoads.map((l) => l[key]), 50)
results.cold_load_median = { ttfb_ms: r1(median('ttfb')), dom_content_loaded_ms: r1(median('dcl')), fcp_ms: r1(median('fcp')) }

await page.goto(url, { waitUntil: 'load' })
await page.waitForTimeout(2500) // let LCP settle and basemap tiles arrive
results.gpu = await page.evaluate(() => {
  const gl = document.createElement('canvas').getContext('webgl2')
  const ext = gl?.getExtension('WEBGL_debug_renderer_info')
  return gl ? gl.getParameter(ext ? ext.UNMASKED_RENDERER_WEBGL : gl.RENDERER) : 'none'
})
results.load = await page.evaluate((origin) => {
  const nav = performance.getEntriesByType('navigation')[0]
  const fcp = performance.getEntriesByName('first-contentful-paint')[0]?.startTime
  const bytes = {}
  for (const r of performance.getEntriesByType('resource')) {
    const own = r.name.startsWith(origin)
    const kind = own ? (r.initiatorType === 'script' || r.name.endsWith('.js') ? 'app js' : r.name.endsWith('.css') ? 'app css' : 'app other') : 'map tiles/style/fonts'
    bytes[kind] = (bytes[kind] ?? 0) + (r.transferSize || r.encodedBodySize || 0)
  }
  return {
    ttfb_ms: nav.responseStart,
    dom_content_loaded_ms: nav.domContentLoadedEventEnd,
    load_ms: nav.loadEventEnd,
    fcp_ms: fcp,
    lcp_ms: window.__perf.lcp,
    cls: window.__perf.cls,
    transfer_kb: Object.fromEntries(Object.entries(bytes).map(([k, v]) => [k, Math.round(v / 1024)])),
  }
}, new URL(url).origin)

// 2. Plan: click an example, time routes on screen and heatmap ready -----------------------
async function planAndMeasure(trigger) {
  const t0 = await now()
  await trigger()
  await page.waitForFunction(() => document.querySelector('.route-card') && !document.querySelector('.map-loading'), null, { timeout: 180_000 })
  const tRoutes = await now()
  await page.waitForFunction(() => document.querySelector('.timeline') && !document.querySelector('.timeline-status'), null, { timeout: 180_000 })
  const tHeat = await now()
  await page.waitForTimeout(300)
  const net = await page.evaluate((t0) => {
    const last = (path) => performance.getEntriesByType('resource').filter((r) => r.name.includes(path) && r.startTime >= t0).at(-1)
    const span = (r) => (r ? r.responseEnd - r.startTime : null)
    const plan = last('/api/plan/')
    const heat = last('/api/heatmap/')
    return { plan_request_ms: span(plan), plan_kb: plan && Math.round(plan.transferSize / 1024), heatmap_request_ms: span(heat), heatmap_kb: heat && Math.round(heat.transferSize / 1024) }
  }, t0)
  const lt = await longTasksSince(t0)
  return {
    routes_visible_ms: tRoutes - t0,
    heatmap_ready_ms: tHeat - t0,
    ...net,
    client_overhead_ms: net.plan_request_ms === null ? null : tRoutes - t0 - net.plan_request_ms,
    long_tasks: lt.length,
    longest_task_ms: lt.length ? Math.max(...lt.map((l) => l.duration)) : 0,
  }
}

results.plan_cold = await planAndMeasure(() => page.getByRole('button', { name: 'Chicago → Nashville' }).click())

// 3. Slider scrubbing: synchronous JS per tick, and input-to-next-frame ---------------------
results.scrub = await page.evaluate(async () => {
  const input = document.querySelector('.slider input')
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set
  const js = []
  const toFrame = []
  for (let i = 0; i < 80; i++) {
    const start = performance.now()
    setter.call(input, String((i * 0.6) % 48))
    input.dispatchEvent(new Event('input', { bubbles: true }))
    js.push(performance.now() - start)
    await new Promise((r) => requestAnimationFrame(() => r()))
    toFrame.push(performance.now() - start)
    await new Promise((r) => setTimeout(r, 30))
  }
  const p = (a, q) => [...a].sort((x, y) => x - y)[Math.round((q / 100) * (a.length - 1))]
  return { js_p50_ms: p(js, 50), js_p95_ms: p(js, 95), input_to_frame_p50_ms: p(toFrame, 50), input_to_frame_p95_ms: p(toFrame, 95) }
})

// 4. Playback: frame rate and jank over 10 s ---------------------------------------------
async function playback(seconds) {
  await page.getByRole('button', { name: 'Play forecast animation' }).click()
  const t0 = await now()
  const before = await scriptSeconds()
  const frames = await page.evaluate(
    (ms) =>
      new Promise((resolve) => {
        const ts = []
        const start = performance.now()
        const tick = (t) => {
          ts.push(t)
          if (t - start < ms) requestAnimationFrame(tick)
          else resolve(ts)
        }
        requestAnimationFrame(tick)
      }),
    seconds * 1000,
  )
  const after = await scriptSeconds()
  await page.getByRole('button', { name: 'Pause forecast animation' }).click()
  const deltas = frames.slice(1).map((t, i) => t - frames[i])
  const lt = await longTasksSince(t0)
  return {
    fps: r1((frames.length - 1) / ((frames.at(-1) - frames[0]) / 1000)),
    frame_p50_ms: r1(pct(deltas, 50)),
    frame_p95_ms: r1(pct(deltas, 95)),
    janky_frames_pct: r1((deltas.filter((d) => d > 33.4).length / deltas.length) * 100),
    script_cpu_pct: r1(((after.script - before.script) / seconds) * 100),
    main_thread_busy_pct: r1(((after.task - before.task) / seconds) * 100),
    long_tasks: lt.length,
  }
}
results.playback = await playback(10)

// 5. Memory: heap after GC, before and after 30 s of playback ---------------------------
const heapMb = async () => {
  await cdp.send('HeapProfiler.collectGarbage')
  const { usedSize } = await cdp.send('Runtime.getHeapUsage')
  return usedSize / 1048576
}
const heapBefore = await heapMb()
await page.getByRole('button', { name: 'Play forecast animation' }).click()
await page.waitForTimeout(30_000)
await page.getByRole('button', { name: 'Pause forecast animation' }).click()
const heapAfter = await heapMb()
results.memory = { heap_before_mb: r1(heapBefore), heap_after_30s_playback_mb: r1(heapAfter), growth_mb: r1(heapAfter - heapBefore) }

// 6. Re-plan with a different load (route + forecast caches are warm) -------------------
results.replan_warm = await planAndMeasure(async () => {
  await page.getByRole('button', { name: '45k' }).click()
  await page.getByRole('button', { name: 'Find the safest route' }).click()
  await page.waitForSelector('.results.stale', { timeout: 5000 }).catch(() => {})
})

await browser.close()

const out = join(dirname(fileURLToPath(import.meta.url)), 'results')
mkdirSync(out, { recursive: true })
writeFileSync(join(out, `browser${throttle > 1 ? `-throttle${throttle}x` : ''}.json`), JSON.stringify(results, null, 2))
console.log(JSON.stringify(results, null, 2))
