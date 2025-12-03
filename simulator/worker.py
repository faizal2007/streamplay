#!/usr/bin/env python3
import os
import time
import json
import shlex
import subprocess
import redis
from datetime import datetime

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

JOB_QUEUE_KEY = "bench_jobs"
JOB_HASH_PREFIX = "bench_job:"
JOB_LOG_PREFIX = "bench_job_log:"

SIMULATOR_SCRIPT = "/simulator/bench_simulator.py"
SIMULATOR_WORKDIR = "/simulator"
RESULTS_DIR = os.path.join(SIMULATOR_WORKDIR, "bench_results")
os.makedirs(RESULTS_DIR, exist_ok=True)

def now_ts():
    return int(time.time())

def log_line(job_id, line):
    key = JOB_LOG_PREFIX + job_id
    try:
        # push to persistent job log list
        r.rpush(key, line)
        # trim to last 2000 lines
        r.ltrim(key, -2000, -1)
        # publish to realtime pubsub channel for streaming to web clients
        payload = json.dumps({"job_id": job_id, "line": line})
        r.publish("bench_logs", payload)
    except Exception:
        # best-effort logging; avoid raising in log path
        pass

def set_job_field(job_id, field, value):
    key = JOB_HASH_PREFIX + job_id
    r.hset(key, field, value)

def process_job(job_item):
    job_id = job_item.get("id")
    params = job_item.get("params", {})
    job_key = JOB_HASH_PREFIX + job_id

    # mark started
    set_job_field(job_id, "status", "running")
    set_job_field(job_id, "started_at", now_ts())

    # Prepare output path for simulator to write
    out_fname = f"bench_result_{job_id}.json"
    out_path = os.path.join(RESULTS_DIR, out_fname)
    # Build command
    cmd = ["python3", SIMULATOR_SCRIPT,
           "--mode", str(params.get("mode", "http")),
           "--url", str(params.get("url")),
           "--concurrency", str(params.get("concurrency", 5)),
           "--duration", str(params.get("duration", 30)),
           "--sample-interval", str(params.get("sample_interval", 1.0)),
           "--think-time", str(params.get("think_time", 1.0)),
           "--screenshot-interval", str(params.get("screenshot_interval", 2.0)),
           "--output", out_path,
           "--safety-factor", str(params.get("safety_factor", 1.5)),
           "--baseline-os-mem-bytes", str(params.get("baseline_os_mem_bytes", 536870912)),
           "--retention-days", str(params.get("retention_days", 7)),
           "--runs-per-day", str(params.get("runs_per_day", 24))
    ]
    targets = params.get("targets", [])
    if isinstance(targets, (list, tuple)):
        for t in targets:
            cmd.extend(["--targets", str(t)])
    elif targets:
        cmd.extend(["--targets", str(targets)])

    try:
        # Start subprocess, capture stdout/stderr merged
        proc = subprocess.Popen(cmd, cwd=SIMULATOR_WORKDIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        # Stream lines to Redis list and publish them for realtime clients
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            line = line.rstrip("\n")
            log_line(job_id, line)
        proc.wait()
        exit_code = proc.returncode
        set_job_field(job_id, "exit_code", str(exit_code))
        if exit_code == 0:
            set_job_field(job_id, "status", "completed")
        else:
            set_job_field(job_id, "status", "failed")
            log_line(job_id, f"Process exited with code {exit_code}")
        set_job_field(job_id, "finished_at", now_ts())
        # If result exists, set result_path in job hash
        if os.path.exists(out_path):
            set_job_field(job_id, "result_path", out_path)
    except Exception as e:
        set_job_field(job_id, "status", "failed")
        set_job_field(job_id, "error", str(e))
        set_job_field(job_id, "finished_at", now_ts())
        log_line(job_id, f"Worker error: {e}")

def main():
    print("Simulator worker started, waiting for jobs...")
    while True:
        try:
            item = r.blpop(JOB_QUEUE_KEY, timeout=0)  # blocks until item
            if not item:
                continue
            _, payload = item
            try:
                job_item = json.loads(payload)
            except Exception as e:
                print("Invalid job payload, skipping:", e)
                continue
            print(f"Picked job {job_item.get('id')}")
            process_job(job_item)
        except Exception as e:
            print("Worker main loop error:", e)
            time.sleep(1)

if __name__ == "__main__":
    main()