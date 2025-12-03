# Proposal: Web-based System Streamer, Test & Benchmark Tool
Author: @copilot (for faizal2007)  
Date: 2025-12-03

Overview
--------
You want a web-based system that can load an arbitrary URL, stream the page to a user, allow that user to interact with the remote page (as if using the remote system), log and record every activity and error, capture screenshots on errors, save test processes, and rerun them automatically. The stack you requested is Python Flask and MariaDB. This proposal describes a practical architecture, components, data model, APIs, UI ideas, implementation plan, milestones, timeline, and risks/mitigations.

High-level architecture
-----------------------
- Frontend: Single-page app (React / Vue / plain JS) served by Flask. Uses WebSocket (Flask-SocketIO) to receive live frames and to send user events (click, type, scroll, JS execution).
- Backend (Flask): HTTP APIs for creating sessions, saving/loading test scripts, starting/stopping runs. A WebSocket endpoint to stream frames and to accept user events in real-time.
- Browser automation worker(s): Headless real browser instances controlled by Playwright (recommended) or Selenium. Each worker runs a browser context for one "live session".
- Background task queue: Celery (with Redis broker) or RQ / APScheduler for scheduled/rerun tasks and long-running runs.
- Database: MariaDB (SQLAlchemy ORM) to store users, sessions, actions, errors, saved processes (scripts), run history, and metadata.
- Storage: Filesystem or object storage (S3-compatible) for screenshots, optional video files and full HAR logs.
- Optional: Redis for session state and messaging between Flask and workers if scaling to multiple machines.
- Observability: Structured logs, Sentry (or self-hosted) for error collection.

Core components and responsibilities
-----------------------------------
- Session Manager (Flask + SocketIO)
  - Create/terminate test sessions
  - Start browser worker and attach to it
  - Relay frames from worker to connected clients (via websocket)
  - Relay user input events from client to worker

- Worker (Playwright)
  - Launch Chrome/Chromium (or Firefox) in headful/headless mode
  - Render the page and capture frames (e.g., as JPEG/PNG) at configurable FPS
  - Receive input events (mouse, keyboard, JS exec) and perform them
  - Capture console logs, network errors, and exceptions
  - Take and store screenshots on errors or on-demand
  - Save HAR, performance metrics and page traces

- Recorder / Action Logger
  - Convert user interactions into serialized action steps (click, type, wait, js)
  - Time-stamp and store each action in MariaDB
  - Provide an exportable test script (JSON/YAML or Selenium/Playwright script)

- Scheduler / Runner
  - Save processes (scripts) and allow reruns (immediate or scheduled)
  - Use Celery/Worker to run saved processes headlessly, generating logs and artifacts
  - Provide rerun reports and deltas vs baseline

- UI
  - Live viewer: show streamed frames; overlay clickable DOM highlight (optional)
  - Controls: start/stop session, view logs, take screenshot, toggle FPS, set viewport
  - Recorder: start recording; list of recorded steps; edit/save process
  - Runner: run saved process; see status and logs; schedule runs
  - Error view: show screenshot, console logs, network failures, tracebacks

Technical choices and justification
-----------------------------------
- Browser automation: Playwright (Python) recommended
  - Pros: modern, multi-browser, builtin recording & tracing, better at headful rendering
  - Alternative: Selenium + ChromeDriver (more mature but heavier)
- Real-time streaming: Flask-SocketIO (websocket) to stream periodic screenshots (e.g., JPEG frames)
  - Pros: simpler to implement and cross-browser
  - Future upgrade: use WebRTC for low-latency streaming (more complexity)
- Background tasks: Celery with Redis
  - Pros: reliable task scheduling & workers for reruns
  - Lightweight alternative: APScheduler for single-host deployments
- DB ORM: SQLAlchemy + Alembic for migrations
- Storage: local filesystem for v1; S3-compatible for production
- Containerization: Docker to package service and worker, with docker-compose for local dev
- Authentication: JWT or session-based authentication (Flask-Login) depending on needs
- Security: sanitize user-supplied URLs, run browsers in isolated containers, limit resource usage, and enforce allowlists/deny lists.

Data model (core tables)
------------------------
- users
  - id, username, password_hash, email, role, created_at

- sessions
  - id, user_id, url, viewport (w/h), created_at, status (live/completed/failed), worker_id

- actions
  - id, session_id, step_index, action_type (click/type/wait/js), selector, value, timestamp, result

- errors
  - id, session_id, action_id (nullable), error_type, message, stacktrace, occurred_at, screenshot_path

- screenshots
  - id, session_id, action_id (nullable), path, taken_at, is_error

- saved_processes (test scripts)
  - id, user_id, name, description, json_script, created_at, last_run_id

- runs
  - id, process_id, started_by, status, started_at, finished_at, result_summary

- artifacts
  - id, run_id, type (har/screenshot/video/trace), path, created_at

API endpoints (examples)
------------------------
- POST /api/sessions
  - body: { "url": "...", "viewport": {w,h}, "record": true/false }
  - creates a session and returns session_id and socket URL

- GET /api/sessions/{id}/status
- POST /api/sessions/{id}/stop
- POST /api/sessions/{id}/screenshot
- WS /ws/sessions/{id}
  - messages from server: { type: "frame", data: base64_jpeg, timestamp }
  - messages from client: { type: "event", event: { action:"click", x, y, selector } }

- POST /api/processes
  - save recorded process

- POST /api/processes/{id}/run
  - start run (immediate) or schedule

- GET /api/runs/{id}/artifacts
- GET /api/errors?session={id}&severity=...

User flows
----------
1. Live test & debug
   - User enters URL and starts a session
   - Browser worker launches and streams JPEG frames via websocket
   - User interacts with streamed page; each event is sent to worker and executed
   - Actions and console/logs are recorded in DB
   - On any error, worker captures screenshot and attaches error record

2. Record & Save Process
   - While interacting, the Recorder stores each action (click/type/wait)
   - User edits and saves process (JSON script) into saved_processes

3. Rerun / Automated Task
   - User schedules or triggers a run of saved_process
   - Worker runs in headless mode via Celery, logs actions, captures errors, produces artifacts (HAR, screenshots)
   - Results and artifacts are available in UI and stored in DB

4. Benchmarking
   - Worker captures performance metrics (TTFB, load time, resource timing)
   - Stress/bench mode: multiple concurrent workers execute same process and metrics are aggregated

Screenshot & error capture strategy
----------------------------------
- On any caught exception, network error, or JS error, take:
  - full-page screenshot (PNG)
  - optional DOM dump (outerHTML)
  - console logs and network failure details
- Name files with timestamp + session/run id; store path in DB
- Keep thumbnails for quick viewing in UI
- For intermittent errors, capture sequences (prior + after) to make debugging easier

Streaming approach (initial + future)
------------------------------------
- v1 (Prototype): Periodic frame capture and WebSocket
  - Worker captures viewport snapshot every X ms (configurable, 1-2 fps default)
  - Encodes as JPEG/PNG base64 and sends via SocketIO
  - Low complexity and cross-browser friendly
- v2 (Improved): WebRTC or MJPEG via HTTP for low-latency streaming
  - Higher complexity; requires TURN/STUN or media server if remote users behind NAT

Security & sandboxing
---------------------
- Run browser workers inside Linux containers (Docker) with resource limits (cpu, memory)
- Network controls: restrict reachable hosts if needed (denylist/allowlist)
- Sanitize and limit URLs (avoid internal network exposure)
- Authentication + role-based access control for users and saved processes
- Rate limit heavy operations (screenshot, start session) to prevent DoS

Scalability & deployment
------------------------
- Single-host for v1 (Flask + Redis + MariaDB + worker)
- For scale:
  - Multiple worker nodes connecting to the same broker (Redis)
  - Sticky session or shared session manager using Redis
  - Object storage for artifacts (S3)
  - Kubernetes for orchestration

Testing strategy
----------------
- Unit tests for Flask endpoints and DB models
- Integration tests with Playwright in CI (use a test worker container)
- E2E tests for recording and rerun flows
- Load tests for benchmarking feature (use locust or k6 to generate concurrent runs)

Deliverables
------------
- Requirements & design doc (this proposal)
- Minimal viable product (MVP):
  - Start/stop session (stream frames)
  - Basic interaction (click, type)
  - Action logging and error screenshot capture
  - Save recorded process and rerun as background job
  - Basic UI to view sessions, actions, errors and artifacts
- CI pipeline, Docker-compose for local dev
- Documentation: setup, run, API spec, runbook for operations

Milestones & estimated timeline (examples)
-----------------------------------------
- Phase 0 — Discovery & detailed requirements: 1 week
- Phase 1 — Prototype (core): 2–3 weeks
  - Flask API + SocketIO
  - Playwright worker streams frames & receives events
  - Basic UI to view and interact
- Phase 2 — Recording, logging & screenshots: 1–2 weeks
  - Action serializer, DB tables, screenshot on error
- Phase 3 — Save/rerun and scheduler: 1–2 weeks
  - Celery tasks + background runs + artifacts
- Phase 4 — UI polish, auth, security hardening: 2–3 weeks
- Phase 5 — Load testing, documentation & handover: 1–2 weeks

Estimated total: 7–12 weeks for a solid MVP (1–2 engineers depending on availability)

Rough resource estimate
-----------------------
- 1 full-time engineer: 8–12 weeks
- 2 engineers (backend + frontend): 5–7 weeks
- Add ops/DevOps for production: +1–2 weeks

Risks and mitigations
---------------------
- Risk: Streaming latency with frame-by-frame approach.
  - Mitigation: Lower FPS for remote access; move to WebRTC for production.
- Risk: Exposing internal network via user-supplied URL.
  - Mitigation: implement allowlist/denylist and network isolation in worker containers.
- Risk: Browser resource leaks on long runs.
  - Mitigation: restart worker periodically, monitor memory, use separate browser contexts per session.
- Risk: Large volume of artifacts (screenshots/HAR).
  - Mitigation: retention policies and object storage.

Next steps (what I did and what I propose next)
-----------------------------------------------
I prepared this proposal that outlines architecture, APIs, data model, components, timeline, and risks tailored to your requirement and the Python Flask + MariaDB stack. Next I can:
- produce a project skeleton (Flask app, SocketIO setup, Playwright worker example, SQLAlchemy models and alembic migrations, docker-compose) and a minimal UI prototype; or
- create a prioritized backlog (issues) and a first-week sprint plan.

Tell me which of the two you prefer and whether you have an existing repo (owner/name) where I should create the initial project, or if you want me to generate the project files here for you to copy into a new repo. I can then create the project skeleton and a runnable demo: open a URL, stream frames, click to interact, and record one sample process.

Appendix: Example DB schema (SQL-ish)
-------------------------------------
- users (id INT PK, username VARCHAR, password_hash VARCHAR, email VARCHAR, role VARCHAR, created_at DATETIME)
- sessions (id INT PK, user_id INT FK, url TEXT, viewport_w INT, viewport_h INT, status VARCHAR, created_at DATETIME)
- actions (id INT PK, session_id INT FK, step_index INT, action_type VARCHAR, selector TEXT, value TEXT, timestamp DATETIME)
- errors (id INT PK, session_id INT FK, action_id INT NULL, error_type VARCHAR, message TEXT, stacktrace TEXT, screenshot_path TEXT, occurred_at DATETIME)
- saved_processes (id INT PK, user_id INT FK, name VARCHAR, json_script TEXT, created_at DATETIME)
- runs (id INT PK, process_id INT FK, started_by INT, status VARCHAR, started_at DATETIME, finished_at DATETIME, summary TEXT)
- artifacts (id INT PK, run_id INT FK, type VARCHAR, path TEXT, created_at DATETIME)

Contact / signature
-------------------
If you want, I can now generate the initial Flask + worker skeleton (with Playwright example) and provide Docker Compose so you can run a local demo. If you want me to push the code to a GitHub repo, share the repo owner/name or confirm I should create files for you to copy.

-- @copilot