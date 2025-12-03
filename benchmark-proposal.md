# Proposal: Capacity-estimation & benchmarking feature for the Streamer system

Goal
----
Let users run a controlled simulation of the streaming/interaction workload and produce an estimated server specification (CPU cores, RAM, disk) for a target concurrency (e.g., 10, 100, 1000 users). The estimate is based on measured resource usage during the simulation and a configurable safety factor and retention assumptions.

Why this is needed
------------------
- Headless browsers (Playwright/Selenium) are resource-heavy and their per-session cost depends on page complexity, screenshot frequency, and recorded artifacts.
- Accurate capacity planning requires measuring real behavior of your app under representative load.
- The system will convert measured per-session CPU / RAM / disk to projected requirements for arbitrary target concurrency.

High-level approach
-------------------
1. Provide a simulation tool that runs N concurrent sessions (two modes):
   - "light" HTTP mode: each session repeatedly issues HTTP requests (cheap, good for purely backend benchmarking).
   - "playwright" mode: each session opens a headless browser context and performs navigation + lightweight interactions + periodic screenshots (realistic for full-browser load).
2. During the test, sample system resource usage periodically:
   - CPU: compute number of logical cores used (sum of per-core % / 100).
   - Memory: used system memory (and optionally process-level memory).
   - Disk: track artifact directory size growth (screenshots/HAR).
   - Network I/O: optional (bytes in/out).
3. At end of run compute average resource usage and per-session footprint:
   - cpu_per_session = avg_total_cores_used / observed_concurrency
   - mem_per_session = avg_used_memory_bytes / observed_concurrency
   - disk_per_session = total_disk_growth_bytes / observed_sessions (or per hour)
4. Extrapolate for a target concurrency:
   - required_cores = ceil(cpu_per_session * target_concurrency * safety_factor)
   - required_ram = mem_per_session * target_concurrency * safety_factor + baseline_os
   - required_disk = (disk_per_session * target_concurrency * retention_days * snapshots_per_session) + baseline_storage
5. Emit an estimation report (human readable + JSON) and raw measurement data for further analysis.

Important caveats
-----------------
- Non-linear behavior: resource usage may not scale linearly (browser memory, CPU contention, GC, IO), so run simulations at multiple concurrency levels and observe scaling behavior.
- Single-machine limits: launching thousands of real headless browsers on a single machine will likely fail; for large concurrency simulate more coarsely, or run distributed simulations across multiple worker machines (or use container orchestration).
- Artifacts (screenshots/HAR) can dominate disk usage — tune screenshot frequency, image quality, and retention.
- For production you’ll usually horizontally scale worker instances (many worker VMs/pods each with X cores & RAM) rather than one massive machine.

Deliverables (what I will add to the skeleton)
----------------------------------------------
- A standalone simulator script (Python) to run local simulation in either `http` or `playwright` mode, sample system metrics, and produce an estimation report.
- Helper functions to convert measured per-session metrics into projected server specs for arbitrary target concurrency and retention assumptions.
- README section explaining how to run simulations and interpret results, and recommended safety factors and production patterns.

Next step
---------
If you want, I will add the simulator script into the project (Playwright + psutil based), wire a sample run for a small concurrency and produce a sample report. Choose:
- "Add simulator now" — I will add the script and usage instructions.
- "Show sample report only" — I will run a small demo locally and give numbers (note: I cannot run code from here, so I will provide hypothetical sample output and explain).

I can proceed to add the simulator files into the project. Tell me "Add simulator now" and I will create the files and instructions here for you to run.