# Performance report

**Short version:**
- A first plan is ready in about 6 s. Nearly all of that is waiting on the routing and
  weather APIs.
- Changing the load or the departure re-plans in **35–200 ms**, because routes and
  forecasts are cached.
- Scrubbing the heatmap costs **about 2–3 ms of JavaScript per tick**.
- Memory stays flat during playback.
- On the test PC, which has **no working GPU driver**, heatmap playback runs at about
  **10 fps**. That limit comes from Chrome rasterising the map in software: during
  playback the page's main thread is about 50% idle.

This testing found and fixed eleven real problems. The fixes are listed at the end,
each with its before/after numbers. It also caught two measurement mistakes, which are
described below so the numbers can be trusted.

All scripts live in [`perf/`](../perf/README.md) and can be rerun.

## How it was measured

| What | How |
| --- | --- |
| Upstream APIs | A local mock ([`perf/mock_upstreams.py`](../perf/mock_upstreams.py)) replays **recorded real OSRM responses** and synthesises Open-Meteo forecasts for any coordinates (with a storm, so risk and heatmap have real work to do). Its latency is calibrated to the real services: OSRM 2 s per request; Open-Meteo 0.5 s plus 20 ms per location. This avoids load-testing free public APIs, and makes runs repeatable. |
| Server | Production settings (`DEBUG=0`) on **waitress** with 16 threads. Waitress stands in for gunicorn, which doesn't run on Windows; both are threaded WSGI servers. |
| Browser | Headless Chrome via Playwright against the production build. Uses CDP for CPU profiles, heap and listener counts, and `PerformanceObserver` for paints and long tasks. The scripts **refuse to report** unless the map canvas is visibly sized, and profiles are taken only after the map has settled. |
| Trips | Dallas → Houston (240 mi), Chicago → Nashville (470 mi), Denver → Salt Lake City (520 mi), and **Los Angeles → Chicago (2,000 mi)** as a stress case. |

**Test machine:** AMD A6-6400K (2 cores, 2013) with 7 GB RAM on Windows 11.
- **WebGL is rendered in software** (Microsoft Basic Render Driver), in every browser
  session on this PC: the GPU driver isn't in use.
- Server, mock and browser all share the same two cores.

Treat everything below as a **worst case**.

## Backend

### Latency with realistic upstream delays (10-mile checkpoints)

| Trip | First plan | Heatmap | Re-plan, cached (new load/departure) | Weather locations used (plan + heatmap) |
| --- | --- | --- | --- | --- |
| Dallas → Houston | 5.7 s | 1.5 s | 34 ms | 64 + 117 |
| Chicago → Nashville | 5.7 s | 1.5 s | 65 ms | 120 + 147 |
| Denver → Salt Lake City | 5.9 s | 1.7 s | 58 ms | 134 + 194 |
| LA → Chicago | 9.5 s | 1.7 s | 203 ms | 544 + 149 |

- A first plan is about **two OSRM round trips (~4 s) plus about 1 s of weather**. That's
  the best case for this design with the public OSRM server.
- **Re-plans make zero upstream calls.**
- **Burst:** four cold plans started at the same moment finished in 10.4 s, about the
  slowest single trip on its own, so there was no contention.

### Throughput with warm caches (CPU-bound; load generator on the same 2 cores)

| Endpoint | 1 client | 4 | 8 | 16 |
| --- | --- | --- | --- | --- |
| `POST /api/plan/` | 15.7 req/s, p50 45 ms | 13.9 req/s, p50 264 ms | 15.5 req/s, p50 508 ms | 16.7 req/s, p50 968 ms |
| `POST /api/heatmap/` | 3.5 req/s, p50 315 ms | 2.8 req/s, p50 1.5 s | 3.1 req/s, p50 2.7 s | 3.9 req/s, p50 4.7 s |

- **No errors at any level.** Throughput is flat from one client upward because the work
  is CPU-bound Python on two cores.
- A heatmap is about **180 ms of pure-Python work**: about 8,000 forecast samples scored
  per request, spread evenly with no single hotspot.
- **Hosting implication:** Render's free instance type is a fraction of a CPU, so expect
  a heatmap to take noticeably longer there. Pick a plan with at least half a CPU for a
  responsive demo.

### CPU cost in-process (no network), before → after the fixes

| Trip | Cached re-plan | Heatmap |
| --- | --- | --- |
| Dallas → Houston | 134 → 21 ms | 213 → 146 ms |
| Chicago → Nashville | 320 → 49 ms | 346 → 193 ms |
| Denver → Salt Lake City | 398 → 62 ms | 474 → 259 ms |
| LA → Chicago | **1,121 → 202 ms** | **1,402 → 364 ms** |

## Frontend (production build, 1440×900 viewport)

Median-of-runs figures from `browser_perf.mjs`, against the warm mock backend:

| Metric | Result |
| --- | --- |
| JS on first load | 80 KB gzipped app code; MapLibre (286 KB gzipped) loads in parallel |
| First contentful paint, cold cache | ~600 ms in the load-only test (784 ms before code-splitting); 750 ms within the full suite |
| Click → routes on screen | 0.8–0.9 s, of which 0.05–0.2 s is the request |
| Click → heatmap ready | 3.0–3.3 s; the heatmap request competes with software rendering for CPU |
| Slider: JS per tick, p50 / p95 | **2.3–2.7 / 27–31 ms** |
| Slider: input → next frame, p50 | 54–70 ms (dominated by the software-rendered repaint) |
| Playback | **9.5–9.8 fps**, frame p50 ~115 ms; script CPU 57–61% (7.7–8.1 fps and 79–84% before the playback fixes) |
| Heap after 30 s of playback | +0.4 MB, flat. DOM listener counts rise and fall back under GC, so nothing leaks. |
| Layout shift (CLS) | 0 |

**Where the playback frame time goes** (`browser_profile.mjs`, steady state, 8 s):

| Share of main thread | |
| --- | --- |
| idle | 53% |
| native / program (GL command marshalling) | 25% |
| MapLibre JS | 13% |
| App code including React | 6% |
| GC | 3% |

The main thread is idle half the time, so the frame rate is bound by the GPU process's
software rasteriser, not by JavaScript. With hardware WebGL that rasterisation cost
largely disappears; how many fps a typical laptop would reach was **not measured here**.

## What was fixed

| Problem | Found by | Fix | Effect |
| --- | --- | --- | --- |
| A cached re-plan re-simplified the full route geometry (20k points) every time; 90% of a re-plan | cProfile in `bench_backend.py` | Simplify once and cache the result with the route; add a radial-distance pre-pass to the simplifier (RDP) | Long-haul re-plan 1,121 → 177 ms |
| The heatmap grid builder tried every spacing from finest to coarsest (9 full builds) | cProfile | Estimate the spacing from route length first; use a byte-mask instead of a set | Long-haul heatmap 1,402 → 347 ms |
| The route de-duplication check ran a binary search per sample (26k per comparison) | cProfile | Walk the segments once instead | Cold long-haul plan −26% CPU |
| Detour routes were requested one after another | Cold latency test | Request them in concurrent pairs, judged in a fixed order | Trips needing 2 detours: 7.6 → 5.7 s |
| The heatmap scored 10k samples through the full `assess()` and lazy settings lookups | cProfile | A level-only function (tested to match `assess()`), with settings read once | Small (~5%) |
| The heatmap was drawn at 8 px per grid cell | Browser CPU profile | 4 px per cell; the GPU's linear filtering keeps it smooth | Paint cost ÷4 |
| Every playback frame re-painted from the grid | Browser CPU profile | Paint each whole hour once per layer; cross-fade cached images in between | Heatmap dropped out of the top profile entries |
| `ImageSource.updateImage` re-laid out tiles and fired metadata events on every frame | Reading MapLibre's source while chasing a playback slowdown | Canvas source updated in place (draw, then `play()`/`pause()`) | No per-frame source reloads |
| The truck layer's `setData` cost a worker round trip, a tile reload and label placement per frame | Listener-churn test | DOM markers | Fewer per-frame jobs; with the two fixes above, playback 8 → 9.7 fps and script CPU 82% → 59% |
| The corridor looked blocky (grid-shaped), with a hard edge where data ended | Visual check | A distance-to-route opacity mask, computed once per heatmap | Smooth band following the roads |
| The whole bundle had to be parsed before first paint | Load timings | Lazy-load the map chunk | Main JS 353 → 80 KB gzipped; FCP 784 → ~600 ms |

**A regression introduced and fixed along the way.** Lazy-loading the map moved
MapLibre's CSS after ours, and an equally specific rule collapsed the map container to
zero height. Screenshots caught it. The browser scripts now check that the map is
visibly sized before reporting anything.

## Measurement mistakes caught (and how they're prevented)

- **Invisible map.** During the collapsed-map regression, playback measured 28 fps and
  the slider 26 ms. Those numbers were meaningless, because a zero-height map has
  nothing to draw. The scripts now assert a visible canvas.
- **Unsettled map.** Profiling right after a plan, while basemap tiles were still
  arriving, measured about 20 fps against a steady state of about 10. `browser_profile`
  now warms the HTTP cache and waits for the map to settle.
- **Windows proxy auto-detection** added about 1.5 s to the first request of every new
  Chrome profile. The scripts launch Chrome with `--no-proxy-server`.
- **Shared CPU.** Software WebGL occupies both cores during map animations, which slows
  the co-located server (e.g. heatmap requests taking 2–3 s in-browser against 1.5 s
  in the load test). End-to-end timings from this machine are pessimistic.

## Known limits

- **Open-Meteo quota.** The free tier allows 600 locations per minute. A 2,000-mile trip
  at 10-mile checkpoints uses about 700 between plan and heatmap, so two such trips in
  one minute will hit the limit. Shorter trips use about 200–330.
- **Heatmap throughput** is bounded by about 180 ms of Python CPU per request. Ways to
  raise it, if needed:
  - more processes, sharing a Redis cache;
  - caching the heatmap per (corridor, departure hour, load);
  - moving the scoring loop to NumPy.
- **No hardware-GPU measurement.** Playback smoothness on typical hardware is
  expected to be much better than on this test machine, but that hasn't been verified.
