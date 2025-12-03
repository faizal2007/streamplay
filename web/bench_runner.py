import os
import uuid
import time
import json
import redis

# Redis-based job queue for benchmark runs.
REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)

JOB_QUEUE_KEY = "bench_jobs"             # list of job JSONs
JOB_HASH_PREFIX = "bench_job:"           # hash per job id: bench_job:<id>
JOB_LOG_PREFIX = "bench_job_log:"        # list per job id: bench_job_log:<id>

RESULTS_DIR = "/simulator/bench_results"  # workers write results here

def _now_ts():
    return int(time.time())

def start_job(params: dict) -> str:
    """
    Create a job record in Redis and push it into the queue.
    Returns job_id.
    """
    job_id = str(uuid.uuid4())
    now = _now_ts()
    job_key = JOB_HASH_PREFIX + job_id
    # Persist the param set and metadata in a hash
    job_meta = {
        "id": job_id,
        "status": "queued",
        "created_at": now,
        "started_at": "",
        "finished_at": "",
        "exit_code": "",
        "result_path": "",
        "error": "",
        "params": json.dumps(params)
    }
    r.hset(job_key, mapping=job_meta)
    # Push to queue: store the job id and params as JSON
    queue_item = {
        "id": job_id,
        "params": params
    }
    r.rpush(JOB_QUEUE_KEY, json.dumps(queue_item))
    return job_id

def get_job(job_id: str):
    job_key = JOB_HASH_PREFIX + job_id
    if not r.exists(job_key):
        return None
    meta = r.hgetall(job_key)
    # parse params if present
    if meta.get("params"):
        try:
            meta["params"] = json.loads(meta["params"])
        except Exception:
            pass
    # fetch logs (last N lines)
    log_key = JOB_LOG_PREFIX + job_id
    logs = r.lrange(log_key, 0, -1) if r.exists(log_key) else []
    # Attempt to load result JSON if result_path exists and accessible
    result = None
    result_path = meta.get("result_path")
    if result_path and os.path.exists(result_path):
        try:
            with open(result_path, "r") as fh:
                result = json.load(fh)
        except Exception:
            result = None
    meta["log"] = logs
    if result is not None:
        meta["result"] = result
    return meta

def list_jobs():
    # Simple scan by key pattern (not ideal at scale)
    keys = r.keys(JOB_HASH_PREFIX + "*")
    return [k.replace(JOB_HASH_PREFIX, "") for k in keys]