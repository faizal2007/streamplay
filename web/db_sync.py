"""
Background synchronizer: periodically scans Redis job hashes and upserts them into DuckDB,
and also ingests newly appended per-job log lines from Redis lists into the DuckDB job_logs table.

Sync strategy for logs:
- Worker pushes lines to Redis list JOB_LOG_PREFIX + job_id.
- We keep a per-job Redis key JOB_LOG_SYNC_PREFIX + job_id storing the next list index to read.
- On each sync iteration we LRANGE from last_index to -1 to get new entries, then insert them into DuckDB with sequence numbers matching Redis list indices.
"""
import os
import time
import threading
import json
import redis
from db.duckdb_client import upsert_job, insert_job_logs

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

JOB_HASH_PREFIX = "bench_job:"
JOB_LOG_PREFIX = "bench_job_log:"
JOB_LOG_SYNC_PREFIX = "bench_job_log_sync:"

SYNC_INTERVAL = float(os.getenv("DB_SYNC_INTERVAL", "1.0"))  # seconds
LOG_BATCH_LIMIT = int(os.getenv("DB_LOG_BATCH_LIMIT", "1000"))

_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

_thread = None
_running = False

def _now_ts():
    return int(time.time())

def _sync_jobs_and_logs_once():
    try:
        keys = _r.keys(JOB_HASH_PREFIX + "*")
        for k in keys:
            try:
                meta = _r.hgetall(k)
                if not meta:
                    continue
                job_id = k.replace(JOB_HASH_PREFIX, "")
                params = None
                if meta.get("params"):
                    try:
                        params = json.loads(meta.get("params"))
                    except Exception:
                        params = meta.get("params")
                job_record = {
                    "id": job_id,
                    "status": meta.get("status"),
                    "created_at": int(meta.get("created_at")) if meta.get("created_at") else None,
                    "started_at": int(meta.get("started_at")) if meta.get("started_at") else None,
                    "finished_at": int(meta.get("finished_at")) if meta.get("finished_at") else None,
                    "exit_code": int(meta.get("exit_code")) if meta.get("exit_code") else None,
                    "result_path": meta.get("result_path"),
                    "error": meta.get("error"),
                    "params": params
                }
                # upsert job metadata into DuckDB
                upsert_job(job_record)
                # now sync logs for this job
                _sync_logs_for_job(job_id)
            except Exception:
                # ignore per-job failures to keep the loop resilient
                continue
    except Exception:
        # top-level ignore to keep loop alive
        pass

def _sync_logs_for_job(job_id: str):
    log_key = JOB_LOG_PREFIX + job_id
    sync_key = JOB_LOG_SYNC_PREFIX + job_id
    # get next index to read (defaults to 0)
    last_idx_val = _r.get(sync_key)
    last_idx = int(last_idx_val) if last_idx_val and last_idx_val.isdigit() else 0
    # get list length
    try:
        llen = _r.llen(log_key)
    except Exception:
        llen = 0
    if llen <= last_idx:
        return  # nothing new
    # fetch new entries (up to batch limit)
    end_idx = min(llen - 1, last_idx + LOG_BATCH_LIMIT - 1)
    try:
        new_entries = _r.lrange(log_key, last_idx, end_idx)
    except Exception:
        new_entries = []
    if not new_entries:
        return
    # prepare rows: (seq, ts, line)
    ts = _now_ts()
    rows = []
    for i, line in enumerate(new_entries):
        seq = last_idx + i
        rows.append((seq, ts, line))
    # insert into DuckDB
    try:
        inserted = insert_job_logs(job_id, rows)
    except Exception:
        inserted = 0
    # advance sync pointer irrespective of insert count to avoid reprocessing duplicates repeatedly
    next_idx = last_idx + len(new_entries)
    try:
        _r.set(sync_key, str(next_idx))
    except Exception:
        pass

def _scan_and_sync():
    global _running
    while _running:
        try:
            _sync_jobs_and_logs_once()
        except Exception:
            pass
        time.sleep(SYNC_INTERVAL)

def start_db_sync():
    global _thread, _running
    if _thread and _thread.is_alive():
        return
    _running = True
    _thread = threading.Thread(target=_scan_and_sync, daemon=True)
    _thread.start()

def stop_db_sync():
    global _running
    _running = False