#!/usr/bin/env python3
"""
Benchmark / capacity estimator for the Streamer system.

Usage (examples):
  # lightweight HTTP mode (cheap, fast)
  python tools/bench_simulator.py --mode http --url https://example.com --concurrency 10 --duration 30

  # playwight mode (real browser load; requires playwright installed & browsers)
  python tools/bench_simulator.py --mode playwright --url https://example.com --concurrency 4 --duration 60 --screenshot-interval 2

What it measures:
 - periodic CPU (sum of per-core usage / 100 -> estimated cores in use)
 - periodic memory used (system)
 - disk growth in artifacts dir
 - approximate per-session CPU/memory/disk and projection to target concurrency

Notes:
 - Playwright mode will open N contexts (a context ~= an "independent browsing session").
 - Running very large concurrency locally with Playwright is likely to exhaust resources; to profile large numbers you should run distributed tests.
"""
import argparse
import asyncio
import base64
import os
import shutil
import signal
import sys
import time
import json
from typing import List, Dict, Any
import psutil

# Optional imports (Playwright)
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except Exception:
    PLAYWRIGHT_AVAILABLE = False

import aiohttp

ARTIFACTS_DIR = "bench_artifacts"

def dir_size_bytes(path: str) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total

async def http_session_worker(session_id: int, url: str, stop_at: float, think_time: float):
    async with aiohttp.ClientSession() as sess:
        while time.time() < stop_at:
            try:
                async with sess.get(url, timeout=20) as r:
                    _ = await r.text()
            except Exception:
                pass
            await asyncio.sleep(think_time)

async def playwright_session_worker(session_id: int, url: str, stop_at: float, screenshot_interval: float):
    if not PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("playwright not installed or browsers not set up")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        # create one context per session (can be adjusted)
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        page = await context.new_page()
        await page.goto(url, timeout=60000)
        last_ss = 0.0
        while time.time() < stop_at:
            try:
                # occasional small interaction: evaluate a no-op
                await page.evaluate("() => document.title")
            except Exception:
                pass
            now = time.time()
            if now - last_ss >= screenshot_interval:
                try:
                    data = await page.screenshot(type="png", full_page=False)
                    # write a small artifact file to measure disk usage
                    fname = os.path.join(ARTIFACTS_DIR, f"sess{session_id}_{int(now)}.png")
                    with open(fname, "wb") as fh:
                        fh.write(data)
                except Exception:
                    pass
                last_ss = now
            await asyncio.sleep(0.2)
        try:
            await context.close()
            await browser.close()
        except Exception:
            pass

async def monitor_task(metrics: Dict[str, List[float]], stop_at: float, sample_interval: float, artifacts_dir: str):
    # metrics: records lists: cpu_cores, mem_used_bytes, disk_bytes
    while time.time() < stop_at:
        try:
            percore = psutil.cpu_percent(interval=None, percpu=True)
            # sum of per-core usage percent -> cores_used approx = sum(percent)/100
            total_cpu_percent = sum(percore)
            cores_used = total_cpu_percent / 100.0
            mem = psutil.virtual_memory().used
            disk = dir_size_bytes(artifacts_dir)
            metrics["cpu_cores"].append(cores_used)
            metrics["mem_used_bytes"].append(mem)
            metrics["disk_bytes"].append(disk)
        except Exception:
            pass
        await asyncio.sleep(sample_interval)

def compute_stats(metrics: Dict[str, List[float]], concurrency: int, duration_seconds: float) -> Dict[str, Any]:
    # compute average values
    def avg(xs):
        return sum(xs) / len(xs) if xs else 0.0
    avg_cores = avg(metrics["cpu_cores"])
    avg_mem = avg(metrics["mem_used_bytes"])
    # disk growth = last - first
    disk_growth = (metrics["disk_bytes"][-1] if metrics["disk_bytes"] else 0) - (metrics["disk_bytes"][0] if metrics["disk_bytes"] else 0)
    # per-session:
    per_session_cores = avg_cores / max(1, concurrency)
    per_session_mem = avg_mem / max(1, concurrency)
    per_session_disk_per_run = disk_growth / max(1, concurrency)
    return {
        "avg_cores": avg_cores,
        "avg_mem_bytes": avg_mem,
        "disk_growth_bytes": disk_growth,
        "per_session_cores": per_session_cores,
        "per_session_mem_bytes": per_session_mem,
        "per_session_disk_bytes": per_session_disk_per_run,
        "observed_concurrency": concurrency,
        "duration_seconds": duration_seconds
    }

def estimate_for_target(stats: Dict[str, Any], target_concurrency: int, safety_factor: float = 1.5, baseline_os_mem_bytes: int = 512 * 1024 * 1024, retention_days: int = 7, runs_per_day: int = 24):
    # CPU:
    cpu_needed = stats["per_session_cores"] * target_concurrency * safety_factor
    cpu_cores = max(1, int(cpu_needed + 0.999))  # ceil to integer cores
    # RAM:
    ram_needed = stats["per_session_mem_bytes"] * target_concurrency * safety_factor + baseline_os_mem_bytes
    # Disk: assume disk per run * runs_per_day * retention_days
    disk_needed_bytes = stats["per_session_disk_bytes"] * target_concurrency * runs_per_day * retention_days * safety_factor
    # Add some baseline
    disk_needed_bytes = disk_needed_bytes + (10 * 1024 * 1024)  # 10MB baseline
    return {
        "target_concurrency": target_concurrency,
        "safety_factor": safety_factor,
        "estimated_cpu_cores": cpu_cores,
        "estimated_ram_bytes": int(ram_needed),
        "estimated_disk_bytes": int(disk_needed_bytes)
    }

def human_bytes(n: int) -> str:
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"

async def run_benchmark(args):
    # prepare artifacts dir
    if os.path.exists(ARTIFACTS_DIR):
        # clear previous
        shutil.rmtree(ARTIFACTS_DIR)
    os.makedirs(ARTIFACTS_DIR, exist_ok=True)

    stop_at = time.time() + args.duration
    metrics = {"cpu_cores": [], "mem_used_bytes": [], "disk_bytes": []}
    # start monitor
    monitor = asyncio.create_task(monitor_task(metrics, stop_at, args.sample_interval, ARTIFACTS_DIR))

    workers = []
    if args.mode == "http":
        for i in range(args.concurrency):
            w = asyncio.create_task(http_session_worker(i, args.url, stop_at, think_time=args.think_time))
            workers.append(w)
    elif args.mode == "playwright":
        if not PLAYWRIGHT_AVAILABLE:
            print("Playwright is not available in this environment. Install playwright and run `playwright install`.", file=sys.stderr)
            return 1
        # for safety, we can spread sessions across browser instances if desired.
        for i in range(args.concurrency):
            w = asyncio.create_task(playwright_session_worker(i, args.url, stop_at, screenshot_interval=args.screenshot_interval))
            workers.append(w)
    else:
        print("Unknown mode", args.mode)
        return 1

    print(f"Started {len(workers)} workers in mode {args.mode}. Sampling every {args.sample_interval}s for {args.duration}s...")
    # Wait for all to finish
    try:
        await asyncio.gather(*workers)
    except asyncio.CancelledError:
        pass
    # Wait a bit to get final monitor sample
    await asyncio.sleep(0.2)
    monitor.cancel()
    # Ensure monitor has last sample
    try:
        await monitor
    except Exception:
        pass

    duration_observed = args.duration
    stats = compute_stats(metrics, args.concurrency, duration_observed)
    # produce estimates for requested target concurrencies
    results = {"stats": stats, "estimates": {}}
    for t in args.targets:
        est = estimate_for_target(stats, t, safety_factor=args.safety_factor,
                                  baseline_os_mem_bytes=args.baseline_os_mem_bytes,
                                  retention_days=args.retention_days,
                                  runs_per_day=args.runs_per_day)
        results["estimates"][str(t)] = est

    # print a friendly report
    print("\n=== Benchmark summary ===")
    print(f"Mode: {args.mode}")
    print(f"Observed concurrency: {stats['observed_concurrency']}")
    print(f"Duration (s): {stats['duration_seconds']}")
    print(f"Average CPU cores used: {stats['avg_cores']:.3f}")
    print(f"Average Memory used: {human_bytes(int(stats['avg_mem_bytes']))}")
    print(f"Disk growth during run: {human_bytes(int(stats['disk_growth_bytes']))}")
    print(f"Per-session CPU (approx): {stats['per_session_cores']:.6f} cores")
    print(f"Per-session Memory (approx): {human_bytes(int(stats['per_session_mem_bytes']))}")
    print(f"Per-session Disk per run (approx): {human_bytes(int(stats['per_session_disk_bytes']))}")

    print("\n=== Projections ===")
    for t, est in results["estimates"].items():
        print(f"\nTarget concurrency: {t}")
        print(f"  safety_factor: {est['safety_factor']}")
        print(f"  estimated CPU cores: {est['estimated_cpu_cores']} cores")
        print(f"  estimated RAM: {human_bytes(est['estimated_ram_bytes'])}")
        print(f"  estimated Disk (for retention policy): {human_bytes(est['estimated_disk_bytes'])}")

    # write JSON results
    out = args.output or "bench_result.json"
    with open(out, "w") as fh:
        json.dump(results, fh, indent=2)
    print(f"\nRaw results written to {out}")
    return 0

def parse_args():
    parser = argparse.ArgumentParser(description="Streamer benchmark & capacity estimator")
    parser.add_argument("--mode", choices=["http", "playwright"], default="http")
    parser.add_argument("--url", required=True)
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--duration", type=int, default=30, help="seconds")
    parser.add_argument("--thumbnail", action="store_true", help="(unused) legacy flag")
    parser.add_argument("--sample-interval", type=float, default=1.0)
    parser.add_argument("--think-time", type=float, default=1.0, help="http worker think time between requests")
    parser.add_argument("--screenshot-interval", type=float, default=2.0, help="playwright screenshot interval (s)")
    parser.add_argument("--targets", nargs="+", type=int, default=[10,50,100,1000], help="target concurrencies to estimate for")
    parser.add_argument("--safety-factor", type=float, default=1.5)
    parser.add_argument("--baseline-os-mem-bytes", type=int, default=512 * 1024 * 1024)
    parser.add_argument("--retention-days", type=int, default=7)
    parser.add_argument("--runs-per-day", type=int, default=24)
    parser.add_argument("--output", type=str, default="bench_result.json")
    return parser.parse_args()

def main():
    args = parse_args()
    loop = asyncio.get_event_loop()
    try:
        rc = loop.run_until_complete(run_benchmark(args))
        sys.exit(rc or 0)
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(1)

if __name__ == "__main__":
    main()