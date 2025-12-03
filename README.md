<<<<<<< HEAD
# streamplay
Streamplay - web streaming, replay and benchmark tool
=======
```markdown
# streamplay

Streamplay is a web-based tool for streaming rendered web pages, interacting with them via a remote browser (Playwright), recording user actions and errors, and running benchmark/simulation jobs to estimate infrastructure requirements. The project provides a Flask + Socket.IO server, Playwright-based workers, a Redis job queue, and DuckDB analytics for persisted job metadata and logs.

This repository contains a runnable skeleton and tools to:
- Start interactive streaming sessions (load a URL, stream periodic screenshots, forward user events).
- Record sessions and capture screenshots on errors.
- Run benchmark simulations (HTTP or real browser Playwright mode) to measure per-session CPU, memory and disk usage.
- Queue benchmark runs via Redis and process them with simulator workers.
- Persist job metadata and logs into DuckDB for history and analytics.
- UI pages to start benchmarks, view live logs, and browse persisted history/results.

Why "streamplay"
- "stream" — live streaming of rendered pages and session activity.
- "play" — interactive playback and Playwright-driven browser automation and replay.

Quickstart (docker-compose)
1. Build images:
   docker-compose build

2. Start core services:
   docker-compose up -d web redis db simulator worker

3. Open the app:
   - Demo/stream client: http://localhost:5000/
   - Benchmark UI: http://localhost:5000/bench
   - Benchmark history: http://localhost:5000/bench/history

Run a simple simulator job locally (example):
- From host (without using the UI):
  docker-compose run --rm simulator python bench_simulator.py --mode http --url https://example.com --concurrency 5 --duration 30

Notes on Playwright mode:
- Playwright mode requires the Playwright browsers. If running in the simulator container, enable playwright install in the simulator Dockerfile (or run `playwright install` on the host).
- Playwright-based simulations are heavier — start with small concurrency values.

Repository contents (high level)
- web/         — Flask server, Socket.IO, UI pages and bench APIs
- worker/      — Playwright worker that streams frames to the server
- simulator/   — simulator scripts and worker that processes benchmark jobs from Redis
- db/          — DuckDB client helpers (jobs and logs persistence)
- bench_artifacts/ — artifacts produced by simulator (screenshots)
- docker-compose.yml, Dockerfiles and requirements.txt

How to publish this repo on GitHub
Option A — I can create the GitHub repository for you:
- Tell me the target owner/org and whether the repo should be public or private (e.g., `faizal2007/streamplay`).
- I will create the repository and push the current skeleton (if you want me to perform the push, grant the necessary repository/create-repo permissions or provide details).

Option B — You can create and push locally:
1. Initialize a Git repo and push to GitHub (replace OWNER and YOUR_TOKEN as needed):
   git init
   git add .
   git commit -m "Initial streamplay skeleton"
   # create repo on GitHub (use GitHub CLI or website)
   # With GitHub CLI:
   gh repo create OWNER/streamplay --public --source=. --remote=origin --push
   # or manually create repo on github.com then:
   git remote add origin https://github.com/OWNER/streamplay.git
   git branch -M main
   git push -u origin main

Recommended next steps
- Run the demo locally and run a few small Playwright simulations to collect baseline metrics.
- Tune screenshot frequency / image quality, and experiment with small concurrency runs (5–20) to extract per-session CPU/memory numbers for extrapolation.
- Add authentication and role-based access control to the web UI.
- Harden sandboxing and resource limits for browser workers (Docker resource limits, container isolation).
- Add CI with tests and a deployment manifest (Kubernetes or a managed container service).

License and contribution
- Choose a license you'd like (MIT, Apache-2.0, etc.). I can add a LICENSE file for you.
- If you want me to push this skeleton to a GitHub repo named `streamplay`, tell me the owner (user/org) and visibility (public/private) and I will proceed.

What I can do next for you
- Create the GitHub repo and push all current files under the chosen owner (I will need the owner name).
- Add a LICENSE file (MIT by default unless you prefer another).
- Create GitHub Actions CI that runs unit checks and builds the Docker images.
- Add a small "Getting started" guide showing example benchmark runs and interpreting results.

Which of these would you like me to do now? If you'd like me to create the GitHub repo and push the code, please provide the target owner (format: owner/streamplay or just an owner) and whether the repo should be public or private.
```
>>>>>>> caa39c4 (Initial streamplay skeleton)
