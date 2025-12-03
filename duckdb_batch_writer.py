import asyncio
import duckdb
import json
import time
from typing import Dict, Any, List

DB_PATH = "streamer.duckdb"
BATCH_SIZE = 500
FLUSH_INTERVAL = 2.0  # seconds

# Example event schema: {
#   "session_id": "...",
#   "timestamp": 1234567890.0,
#   "type": "click" | "type" | "error" | "navigation",
#   "payload": {...}  # JSON-serializable arbitrary metadata
# }

class DuckDBWriter:
    def __init__(self, db_path: str = DB_PATH):
        self.conn = duckdb.connect(db_path)
        self._ensure_table()

    def _ensure_table(self):
        # events table with JSON in a text column (DuckDB can query JSON strings)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id BIGINT AUTOINCREMENT PRIMARY KEY,
            session_id VARCHAR,
            ts DOUBLE,
            type VARCHAR,
            payload VARCHAR
        )
        """)

    def insert_batch(self, rows: List[Dict[str, Any]]):
        if not rows:
            return
        # Prepare parameter tuples
        params = [(r["session_id"], float(r["timestamp"]), r["type"], json.dumps(r.get("payload", {}))) for r in rows]
        # Use executemany for efficiency
        self.conn.executemany("INSERT INTO events (session_id, ts, type, payload) VALUES (?, ?, ?, ?)", params)
        # Optional: checkpoint/flush (DuckDB writes to disk on commit)
        # conn.commit() not needed in duckdb python API as operations are synchronous
        return len(params)

async def event_producer(queue: asyncio.Queue):
    # Demo producer that generates events (in real app, workers push to queue)
    i = 0
    while True:
        evt = {
            "session_id": f"session-{i % 3}",
            "timestamp": time.time(),
            "type": "click" if i % 5 else "navigation",
            "payload": {"x": i, "y": i * 2, "meta": f"event-{i}"}
        }
        await queue.put(evt)
        i += 1
        await asyncio.sleep(0.01)  # produce ~100 events/sec in demo

async def batched_writer_task(queue: asyncio.Queue, writer: DuckDBWriter):
    buffer: List[Dict[str, Any]] = []
    last_flush = time.time()
    while True:
        try:
            # Wait for next item with timeout to allow periodic flush
            evt = await asyncio.wait_for(queue.get(), timeout=FLUSH_INTERVAL)
            buffer.append(evt)
            # If batch size reached, write now
            if len(buffer) >= BATCH_SIZE:
                n = writer.insert_batch(buffer)
                print(f"Flushed batch size {n}")
                buffer.clear()
                last_flush = time.time()
            queue.task_done()
        except asyncio.TimeoutError:
            # Timeout -> flush if there are buffered events
            if buffer:
                n = writer.insert_batch(buffer)
                print(f"Flushed on timeout {n}")
                buffer.clear()
                last_flush = time.time()
        except Exception as e:
            print("Writer error:", e)

async def main_demo():
    queue = asyncio.Queue()
    writer = DuckDBWriter()
    # Start the writer task
    writer_task = asyncio.create_task(batched_writer_task(queue, writer))
    # Start a demo producer (replace in real app by workers pushing to the queue)
    prod_task = asyncio.create_task(event_producer(queue))
    await asyncio.gather(writer_task, prod_task)

if __name__ == "__main__":
    try:
        asyncio.run(main_demo())
    except KeyboardInterrupt:
        print("Stopped")