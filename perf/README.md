# Performance tests

These tests never call the public routing or weather APIs. Results:
[docs/PERFORMANCE.md](../docs/PERFORMANCE.md).

| Script | Measures |
| --- | --- |
| `mock_upstreams.py` | Local OSRM / Open-Meteo / Photon stand-in: recorded routes, synthetic forecasts, realistic latency |
| `bench_backend.py` | In-process CPU cost of planning and heatmaps (`--profile` for cProfile hotspots) |
| `load_test.py` | Cold first-plan latency and upstream call counts, a cold burst, warm throughput by concurrency |
| `serve.py` | Production build + mock upstreams on `http://127.0.0.1:8001`, for browser tests or manual use |
| `browser_perf.mjs` | Paint timings, click-to-routes and click-to-heatmap, slider cost, playback fps/jank, memory, re-plan |
| `browser_profile.mjs` | CPU profile of heatmap playback, by bundle and function |

## Running

Use the backend's virtualenv. The load tests also need `waitress`.

```bash
backend/.venv/Scripts/pip install waitress           # bin/pip on macOS/Linux

# Backend
backend/.venv/Scripts/python perf/bench_backend.py --profile
backend/.venv/Scripts/python perf/load_test.py all  # ~4 min; saves perf/results/backend-all.json

# Frontend: build, start the stack, then run the browser scripts in another terminal
cd frontend && npm run build && cp -r dist ../backend/frontend_dist && cd ..
backend/.venv/Scripts/python perf/serve.py
cd perf && npm install && node browser_perf.mjs && node browser_profile.mjs
```

The browser scripts default to Chrome at `C:/Program Files/Google/Chrome/Application/chrome.exe`.
Set `CHROME_PATH` to use another browser. Add `--cpu-throttle=4` to `browser_perf.mjs`
to emulate a slower device.

**OSRM fixtures.** `fixtures/osrm/` holds recorded responses for the four test trips.
If routing logic changes which requests are made, record the new ones once (this needs
internet access):

```bash
backend/.venv/Scripts/python perf/load_test.py record
```
