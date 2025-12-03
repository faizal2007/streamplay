# Full web app including the new /api/bench/history enhancement that includes inline metrics
import os
import uuid
import json
from flask import Flask, request, jsonify, send_from_directory, send_file
from flask_socketio import SocketIO, emit, join_room
from dotenv import load_dotenv
from bench_runner import start_job, get_job
from log_listener import register_emit_callback, start_redis_listener
from db_sync import start_db_sync
from db.duckdb_client import get_recent_jobs, get_job_logs, get_job_by_id

load_dotenv()

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config['SECRET_KEY'] = os.getenv("SECRET_KEY", "dev-secret")

# Use eventlet for Socket.IO server
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

# Start Redis listener and DB sync; register emit callback to forward logs via Socket.IO
def _emit_to_socketio(job_id, line):
    room = f"bench_job:{job_id}"
    socketio.emit("bench_log", {"job_id": job_id, "line": line}, room=room)

register_emit_callback(_emit_to_socketio)
start_redis_listener()
start_db_sync()

SESSIONS = {}

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

@app.route("/bench")
def bench_ui():
    return send_from_directory(app.static_folder, "benchmark.html")

@app.route("/bench/history")
def bench_history_ui():
    return send_from_directory(app.static_folder, "history.html")

@app.route("/api/bench/start", methods=["POST"])
def api_bench_start():
    payload = request.json or {}
    required = ["mode", "url", "concurrency", "duration"]
    for r in required:
        if r not in payload:
            return jsonify({"error": f"{r} is required"}), 400
    params = {
        "mode": payload.get("mode", "http"),
        "url": payload.get("url"),
        "concurrency": int(payload.get("concurrency", 5)),
        "duration": int(payload.get("duration", 30)),
        "sample_interval": float(payload.get("sample_interval", 1.0)),
        "think_time": float(payload.get("think_time", 1.0)),
        "screenshot_interval": float(payload.get("screenshot_interval", 2.0)),
        "targets": payload.get("targets", [10,50,100,1000]),
        "safety_factor": float(payload.get("safety_factor", 1.5)),
        "baseline_os_mem_bytes": int(payload.get("baseline_os_mem_bytes", 512 * 1024 * 1024)),
        "retention_days": int(payload.get("retention_days", 7)),
        "runs_per_day": int(payload.get("runs_per_day", 24))
    }
    job_id = start_job(params)
    return jsonify({"job_id": job_id}), 202

@app.route("/api/bench/status/<job_id>", methods=["GET"])
def api_bench_status(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    return jsonify(job)

@app.route("/api/bench/result/<job_id>", methods=["GET"])
def api_bench_result(job_id):
    job = get_job(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    result_path = job.get("result_path")
    if not result_path or not os.path.exists(result_path):
        return jsonify({"error": "result not available"}), 404
    return send_file(result_path, mimetype="application/json", as_attachment=True, download_name=f"bench_result_{job_id}.json")

def _human_bytes(n):
    try:
        n = int(n)
    except Exception:
        return "-"
    for unit in ['B','KB','MB','GB','TB']:
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}PB"

def _load_summary_from_result_path(result_path):
    """
    Try to load the simulator result JSON and extract key metrics for inline display.
    Returns a dict (may be empty on failure).
    Expected structure in result JSON:
      {
        "stats": {
          "avg_cores": ...,
          "avg_mem_bytes": ...,
          "disk_growth_bytes": ...,
          "per_session_cores": ...,
          "per_session_mem_bytes": ...,
          ...
        },
        "estimates": {...}
      }
    """
    if not result_path or not os.path.exists(result_path):
        return None
    try:
        with open(result_path, "r") as fh:
            data = json.load(fh)
    except Exception:
        return None
    stats = data.get("stats") or data.get("stats", {})
    if not stats and "stats" in data:
        stats = data["stats"]
    # tolerate nested structure used earlier (top-level "stats")
    s = data.get("stats", {}) if isinstance(data.get("stats", {}), dict) else {}
    # fallback: if top-level keys present
    s = s or data.get("stats", {}) or {}
    # Some simulator variants put stats at data["stats"]
    stats = data.get("stats", {}) or stats or {}
    # Build summary
    try:
        avg_cores = float(stats.get("avg_cores") or 0.0)
    except Exception:
        avg_cores = 0.0
    try:
        avg_mem = int(stats.get("avg_mem_bytes") or 0)
    except Exception:
        avg_mem = 0
    try:
        disk_growth = int(stats.get("disk_growth_bytes") or 0)
    except Exception:
        disk_growth = 0
    try:
        per_session_cores = float(stats.get("per_session_cores") or 0.0)
    except Exception:
        per_session_cores = 0.0
    try:
        per_session_mem = int(stats.get("per_session_mem_bytes") or 0)
    except Exception:
        per_session_mem = 0
    return {
        "avg_cores": avg_cores,
        "avg_cores_str": f"{avg_cores:.3f}",
        "avg_mem_bytes": avg_mem,
        "avg_mem": _human_bytes(avg_mem),
        "disk_growth_bytes": disk_growth,
        "disk_growth": _human_bytes(disk_growth),
        "per_session_cores": per_session_cores,
        "per_session_cores_str": f"{per_session_cores:.6f}",
        "per_session_mem_bytes": per_session_mem,
        "per_session_mem": _human_bytes(per_session_mem)
    }

# New: jobs history endpoint retrieving metadata from DuckDB and inline summaries
@app.route("/api/bench/history", methods=["GET"])
def api_bench_history():
    limit = int(request.args.get("limit", 100))
    jobs = get_recent_jobs(limit=limit)
    # Augment each job with inline summary (if result file available)
    for job in jobs:
        result_path = job.get("result_path")
        summary = _load_summary_from_result_path(result_path) if result_path else None
        job["summary"] = summary
    return jsonify({"jobs": jobs})

# New: fetch persisted logs from DuckDB
@app.route("/api/bench/logs/<job_id>", methods=["GET"])
def api_bench_logs(job_id):
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 1000))
    logs = get_job_logs(job_id, offset=offset, limit=limit)
    return jsonify({"job_id": job_id, "logs": logs})

# SocketIO handlers (unchanged)
@socketio.on("join")
def on_join(data):
    session_id = data.get("session_id")
    if not session_id:
        return
    join_room(session_id)
    emit("joined", {"session_id": session_id})

@socketio.on("register_worker")
def on_register_worker(data):
    join_room("workers")
    emit("worker_registered", {"ok": True})

@socketio.on("frame")
def on_frame(data):
    session_id = data.get("session_id")
    if not session_id:
        return
    socketio.emit("frame", {"session_id": session_id, "data": data.get("data")}, room=session_id)

@socketio.on("event")
def on_event(data):
    socketio.emit("event", data, room="workers")

# Clients can subscribe to real-time bench logs via Socket.IO
@socketio.on("bench_subscribe")
def on_bench_subscribe(data):
    job_id = data.get("job_id")
    if not job_id:
        emit("bench_subscribed", {"ok": False, "error": "job_id required"})
        return
    room = f"bench_job:{job_id}"
    join_room(room)
    emit("bench_subscribed", {"ok": True, "job_id": job_id})

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)