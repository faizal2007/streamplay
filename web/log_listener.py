import threading
import json
import time
import os
import redis

# This module subscribes to the Redis pubsub channel 'bench_logs' and
# forwards messages to the Flask-SocketIO server via a callback that the
# web app registers at startup.
#
# Usage:
#   from log_listener import start_redis_listener, stop_redis_listener, register_emit_callback
#   register_emit_callback(your_emit_function)
#   start_redis_listener()
#
# The emit callback will be called with two args: (job_id, line)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))

_channel = "bench_logs"
_r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)
_thread = None
_running = False
_emit_cb = None

def register_emit_callback(cb):
    """
    cb should be a callable like cb(job_id: str, line: str)
    """
    global _emit_cb
    _emit_cb = cb

def _listener_loop():
    global _running
    ps = _r.pubsub()
    ps.subscribe(_channel)
    _running = True
    try:
        for message in ps.listen():
            # message example: {'type': 'message', 'pattern': None, 'channel': 'bench_logs', 'data': '{"job_id": "...", "line": "..."}'}
            if not _running:
                break
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            data = message.get("data")
            if not data:
                continue
            try:
                payload = json.loads(data)
                job_id = payload.get("job_id")
                line = payload.get("line")
                if _emit_cb and job_id and line is not None:
                    try:
                        _emit_cb(job_id, line)
                    except Exception:
                        pass
            except Exception:
                # ignore malformed payloads
                pass
    finally:
        try:
            ps.close()
        except Exception:
            pass
        _running = False

def start_redis_listener():
    global _thread
    if _thread and _thread.is_alive():
        return
    _thread = threading.Thread(target=_listener_loop, daemon=True)
    _thread.start()

def stop_redis_listener():
    global _running
    _running = False