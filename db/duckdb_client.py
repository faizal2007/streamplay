import duckdb
import os
import json
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple

DB_PATH = os.getenv("DUCKDB_PATH", "/data/streamer.duckdb")

_conn: Optional[duckdb.DuckDBPyConnection] = None

def get_conn():
    global _conn
    if _conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _conn = duckdb.connect(DB_PATH)
        _ensure_schema(_conn)
    return _conn

def _ensure_schema(conn):
    # jobs table: store metadata and params as JSON string
    conn.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id VARCHAR PRIMARY KEY,
        status VARCHAR,
        created_at BIGINT,
        started_at BIGINT,
        finished_at BIGINT,
        exit_code INTEGER,
        result_path VARCHAR,
        error VARCHAR,
        params VARCHAR,
        last_updated BIGINT
    );
    """)
    # job_logs: per-line logs persisted with sequence index to avoid duplicates
    conn.execute("""
    CREATE TABLE IF NOT EXISTS job_logs (
        job_id VARCHAR,
        seq BIGINT,
        ts BIGINT,
        line VARCHAR,
        PRIMARY KEY (job_id, seq)
    );
    """)
    # index for faster reads
    conn.execute("CREATE INDEX IF NOT EXISTS idx_job_logs_job ON job_logs(job_id);")

def upsert_job(job: Dict[str, Any]):
    """
    Upsert a job record into the jobs table.
    job keys: id, status, created_at, started_at, finished_at, exit_code, result_path, error, params
    """
    conn = get_conn()
    now = int(datetime.utcnow().timestamp())
    params = job.get("params")
    if params is not None and not isinstance(params, str):
        try:
            params = json.dumps(params)
        except Exception:
            params = str(params)
    # Use delete+insert to emulate upsert (safe single-writer pattern)
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("DELETE FROM jobs WHERE id = ?", (job["id"],))
        conn.execute(
            "INSERT INTO jobs (id, status, created_at, started_at, finished_at, exit_code, result_path, error, params, last_updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job.get("id"),
                job.get("status"),
                int(job.get("created_at") or 0),
                int(job.get("started_at") or 0),
                int(job.get("finished_at") or 0),
                int(job.get("exit_code")) if job.get("exit_code") not in (None, "") else None,
                job.get("result_path"),
                job.get("error"),
                params,
                now
            )
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

def insert_job_logs(job_id: str, rows: List[Tuple[int, int, str]]):
    """
    Insert a batch of log rows for job_id.
    rows: list of tuples (seq, ts, line)
    This respects the PRIMARY KEY (job_id, seq) and will error on duplicates.
    We run inside a transaction and ignore duplicate-key errors by filtering beforehand.
    """
    if not rows:
        return 0
    conn = get_conn()
    # Find existing seqs to avoid duplicate insert attempts
    seqs = [r[0] for r in rows]
    min_seq = min(seqs)
    max_seq = max(seqs)
    # Retrieve already present sequences in range (fast)
    existing = conn.execute(
        "SELECT seq FROM job_logs WHERE job_id = ? AND seq BETWEEN ? AND ?",
        (job_id, min_seq, max_seq)
    ).fetchall()
    existing_seqs = {r[0] for r in existing} if existing else set()
    to_insert = [r for r in rows if r[0] not in existing_seqs]
    if not to_insert:
        return 0
    conn.execute("BEGIN TRANSACTION")
    try:
        # Use executemany for batch insert
        params = [(job_id, seq, ts, line) for (seq, ts, line) in to_insert]
        conn.executemany("INSERT INTO job_logs (job_id, seq, ts, line) VALUES (?, ?, ?, ?)", params)
        conn.execute("COMMIT")
        return len(to_insert)
    except Exception:
        conn.execute("ROLLBACK")
        raise

def get_recent_jobs(limit: int = 100) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT id, status, created_at, started_at, finished_at, exit_code, result_path, error, params, last_updated FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        params = None
        if r[8]:
            try:
                params = json.loads(r[8])
            except Exception:
                params = r[8]
        out.append({
            "id": r[0],
            "status": r[1],
            "created_at": r[2],
            "started_at": r[3],
            "finished_at": r[4],
            "exit_code": r[5],
            "result_path": r[6],
            "error": r[7],
            "params": params,
            "last_updated": r[9]
        })
    return out

def get_job_by_id(job_id: str) -> Optional[Dict[str, Any]]:
    conn = get_conn()
    try:
        res = conn.execute("SELECT id, status, created_at, started_at, finished_at, exit_code, result_path, error, params, last_updated FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if not res:
            return None
        params = None
        if res[8]:
            try:
                params = json.loads(res[8])
            except Exception:
                params = res[8]
        return {
            "id": res[0],
            "status": res[1],
            "created_at": res[2],
            "started_at": res[3],
            "finished_at": res[4],
            "exit_code": res[5],
            "result_path": res[6],
            "error": res[7],
            "params": params,
            "last_updated": res[9]
        }
    except Exception:
        return None

def get_job_logs(job_id: str, offset: int = 0, limit: int = 1000) -> List[Dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute("SELECT seq, ts, line FROM job_logs WHERE job_id = ? AND seq >= ? ORDER BY seq ASC LIMIT ?", (job_id, offset, limit)).fetchall()
    out = []
    for r in rows:
        out.append({"seq": r[0], "ts": r[1], "line": r[2]})
    return out