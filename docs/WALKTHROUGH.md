# Loom walkthrough outline (about 8 minutes)

Talking points for the 5–10 minute walkthrough the brief asks for. Times are targets.

## 1. The problem and the demo (0:00 – 2:30)
- One sentence: pick the safest route using the weather the truck will hit **when it
  gets there**, the load weight and the travel time.
- Click **Chicago → Nashville**, and point out:
  - the three route options, ordered by rank;
  - the recommended route and the sentence explaining why it beat each of the others;
  - route lines colored by risk;
  - a checkpoint popup showing ETA, wind/gust, rain, snow and the reason for its level.
- Change the load to **45k** and re-plan. Re-plans are near-instant because of caching.
  Show a wind checkpoint escalating to Severe (35–44 mph above 40,000 lb).
- Switch the interval between 10, 25 and 50 miles and show the checkpoint count change.

## 2. Heatmap and slider (2:30 – 4:00)
- Drag the slider: the heatmap blends smoothly between hours, and the truck markers move
  along every route at that time.
- Press play. Switch between the Risk, Wind, Rain and Snow layers. The legend ticks sit
  exactly on the risk thresholds.
- Hover the map to read the value under the cursor.
- Click a checkpoint row: the map flies to it and the slider jumps to its ETA, so you
  see the same forecast the risk was computed from.

## 3. Logic that drives the 40% (4:00 – 6:00)
- Open "How risk is scored".
- Explain the boundary convention: the table repeats its boundary values, and the
  explicit "≥ 55" and "> 1.00" endpoints decide which band each boundary belongs to.
- Load rules escalate only the wind level. A checkpoint takes the worst condition.
- Each checkpoint represents the half-interval on either side of it, so per-level
  miles always add up to the route length.
- Ranking:
  - No Travel miles come first; I added this because the brief's list omits No Travel;
  - then Severe miles, High miles, average risk and travel time;
  - ties are compared at a fixed precision.
- Routes:
  - OSRM alternatives, topped up with via-point detours;
  - candidates are filtered for overlap and slowness;
  - out-and-back spurs are trimmed;
  - truck speed is capped.
- ETA alignment: wind is interpolated between hours, and precipitation uses the bucket
  for the hour ending after the ETA.

## 4. Engineering (6:00 – 7:30)
- Backend layout:
  - `domain/` is pure and unit-tested;
  - `providers/` are thin API clients;
  - `services/` are the use cases.
- Weather: each location is fetched once for a fixed window and cached, so changing the
  departure or the load costs no new calls. This matters because of Open-Meteo's
  600-calls-per-minute limit.
- Heatmap rendering:
  - the frontend renders the grid itself, with a Mercator correction and bilinear
    interpolation;
  - pixels go straight to the GPU texture, at about 1.5 ms of JS per frame;
  - mention the perf suite: mocked upstreams, profiles, and the fixes in docs/PERFORMANCE.md;
  - the sidebar is memoised, so scrubbing doesn't re-render it.
- Tests, CI, and a single Docker image serving both the API and the SPA.

## 5. Limitations and next steps (7:30 – 8:00)
- Use a truck-specific router (HERE truck routing or ORS hgv).
- Add hours-of-service rest breaks to the ETAs.
- Move the cache to Redis to support multiple instances.
