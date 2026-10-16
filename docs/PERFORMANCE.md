# Performance report

**Short version:**
- A first plan is ready in about 6 s. Nearly all of that is waiting on the routing and
  weather APIs.
- Changing the load or the departure re-plans in **35–200 ms**, because routes and
  forecasts are cached.
- Scrubbing the heatmap costs **about 1.5 ms of JavaScript per tick**.
- Playback holds **about 28 fps on a 2013 dual-core with no GPU driver**. On an ordinary
  laptop with hardware WebGL it should be considerably smoother, but that was not
  measured.
- Memory stays flat during playback.

This testing found and fixed eight real bottlenecks. The fixes are listed at the end,
each with its before/after numbers.

All scripts live in [`perf/`](../perf/README.md) and can be rerun.

## How it was measured

| What | How |
| --- | --- |
| Upstream APIs | A local mock ([`perf/mock_upstreams.py`](../perf/mock_upstreams.py)) replays **recorded real OSRM responses** and synthesises Open-Meteo forecasts for any coordinates (with a storm, so risk and heatmap have real work to do). Its latency is calibrated to the real services: OSRM 2 s per request; Open-Meteo 0.5 s plus 20 ms per location. This avoids load-testing free public APIs, and makes runs repeatable. |
| Server | Production settings (`DEBUG=0`) on **waitress** with 16 threads. Waitress stands in for gunicorn, which doesn't run on Windows; both are threaded WSGI servers. |
| Browser | Headless Chrome via Playwright against the production build. Uses CDP for CPU profiles and heap measurements, and `PerformanceObserver` for paints and long tasks. |
| Trips | Dallas → Houston (240 mi), Chicago → Nashville (470 mi), Denver → Salt Lake City (520 mi), and **Los Angeles → Chicago (2,000 mi)** as a stress case. |

**Test machine:** AMD A6-6400K (2 cores, 2013) with 7 GB RAM on Windows 11.
- **WebGL is rendered in software** (Microsoft Basic Render Driver), in every browser
  session on this PC: the GPU driver isn't in use.
- Server, mock and browser all share the same two cores.

So treat everything below as a **worst case**. Frame-rate figures in particular are
limited by software rasterisation: halving the viewport's width and height raised
playback from 8 to 20 fps before the optimisations below.

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

## Frontend (production build)

| Metric | Result |
| --- | --- |
| JS on first load | 80 KB gzipped for the app; the map library loads separately (286 KB gzipped) |
| First contentful paint, cold cache (median of 5) | ~690 ms (~780 ms before code-splitting) |
| Click → routes on screen (server cache warm) | 0.7–1.0 s, of which ~0.2 s is the request |
| Click → heatmap ready | 2.1–3.2 s |
| Slider: JS per tick, p50 / p95 | **1.5 / 3.4 ms** (3.9 / 43 ms before) |
| Slider: input → next frame, p50 | **26 ms** |
| Playback | **28 fps**, frame p95 61 ms, no long tasks (8 fps / 128 ms before) |
| Heap after 30 s of playback | Flat (−0.3 to +0.9 MB): no leak |
| Layout shift (CLS) | 0 |

Where main-thread time goes during playback, at the start of tuning:
- **Map drawing (MapLibre):** most of it, plus about 30% native time, which is the
  software GL renderer.
- **Our heatmap renderer:** about 12%.

After the fixes, the heatmap renderer is about 5% of main-thread time.

## What was fixed

| Problem | Found by | Fix | Effect |
| --- | --- | --- | --- |
| A cached re-plan re-simplified the full route geometry (20k points) every time; 90% of a re-plan | cProfile in `bench_backend.py` | Simplify once and cache the result with the route; add a radial-distance pre-pass to the simplifier (RDP) | Long-haul re-plan 1,121 → 177 ms |
| The heatmap grid builder tried every spacing from finest to coarsest (9 full builds) | cProfile | Estimate the spacing from route length first; use a byte-mask instead of a set | Long-haul heatmap 1,402 → 347 ms |
| The route de-duplication check ran a binary search per sample (26k per comparison) | cProfile | Walk the segments once instead | Cold long-haul plan −26% CPU |
| Detour routes were requested one after another | Cold latency test | Request them in concurrent pairs, judged in a fixed order | Trips needing 2 detours: 7.6 → 5.7 s |
| The heatmap scored 10k samples through the full `assess()` and lazy settings lookups | cProfile | A level-only function (tested to match `assess()`), with settings read once | Small (~5%) |
| The heatmap was drawn at 8 px per grid cell | Browser CPU profile | 4 px per cell; the GPU's linear filtering keeps it smooth | Heatmap share of main thread 12% → 5% |
| The corridor looked blocky (grid-shaped), with a hard edge where data ended | Visual check while tuning | A distance-to-route opacity mask, computed once per heatmap | Smooth band following the roads |
| The whole bundle had to be parsed before first paint | Load timings | Lazy-load the map chunk | Main JS 353 → 80 KB gzipped; FCP −10–27% |

## Measurement pitfalls found along the way

- **Windows proxy auto-detection** added about 1.5 s to the first request of every new
  Chrome profile. The browser scripts launch Chrome with `--no-proxy-server`.
- **Software WebGL makes everything look slower.** It occupies both cores during map
  animations, which also slowed the co-located server; one cached re-plan measured
  1.8 s in-browser against under 0.1 s server-side. End-to-end timings from this
  machine are pessimistic.
- **Early runs of this PC's network stalled TLS handshakes** to the public APIs. That's
  why all load testing uses the mock, and why the backend now has short connect timeouts
  with retries (see the main README).

## Known limits

- **Open-Meteo quota.** The free tier allows 600 locations per minute. A 2,000-mile trip
  at 10-mile checkpoints uses about 700 between plan and heatmap, so two such trips in
  one minute will hit the limit. Shorter trips use about 200–330.
- **Heatmap throughput** is bounded by about 180 ms of Python CPU per request. Ways to
  raise it, if needed:
  - more processes, sharing a Redis cache;
  - caching the heatmap per (corridor, departure hour, load);
  - moving the scoring loop to NumPy.
