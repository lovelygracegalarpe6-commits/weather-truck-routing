"""Run the production build against the mock upstreams, for browser tests or manual poking.

    python perf/serve.py [--latency none]      # app on http://127.0.0.1:8001

The frontend must be built into backend/frontend_dist first:
    cd frontend && npm run build && cp -r dist ../backend/frontend_dist
"""

from __future__ import annotations

import argparse
import time

from common import BACKEND, running_stack


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency", choices=["realistic", "none"], default="realistic")
    args = parser.parse_args()
    if not (BACKEND / "frontend_dist" / "index.html").exists():
        raise SystemExit("No frontend build in backend/frontend_dist (see this file's docstring).")
    with running_stack(latency=args.latency, log_name="serve") as (app, _):
        print(f"serving {app}  (mock upstreams, latency={args.latency}); Ctrl+C to stop", flush=True)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
