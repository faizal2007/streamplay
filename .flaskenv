# Flask-specific environment variables for local development.
# Copy this file to the project root and update values before running.
# Do NOT commit secrets to a public repo.

FLASK_APP=web/app.py
FLASK_ENV=development
SECRET_KEY=change-me-to-a-strong-random-value

# Redis (job queue / pubsub)
REDIS_HOST=192.168.1.5
REDIS_PORT=6379
REDIS_DB=0

# Socket.IO / message queue
SOCKETIO_MESSAGE_QUEUE=redis://redis:6379/0
SOCKETIO_SERVER=http://localhost:5000

# Database / analytics
# Example MariaDB URL (if using MariaDB): mysql+pymysql://user:pass@db:3306/streamer
# Example DuckDB path (used by analytics): file path accessible to web container
DATABASE_URL=mysql+pymysql://root:example@db:3306/streamer
DUCKDB_PATH=/data/streamer.duckdb

# Simulator / artifacts
SIMULATOR_SCRIPT=/simulator/bench_simulator.py
SIMULATOR_WORKDIR=/simulator
ARTIFACTS_DIR=/simulator/bench_artifacts

# Optional tuning
LOG_LEVEL=INFO
