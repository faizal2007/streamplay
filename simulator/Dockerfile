FROM python:3.11-slim

WORKDIR /simulator

# System deps (minimal) - psutil/build tools
RUN apt-get update && apt-get install -y \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY ../requirements.txt /simulator/requirements.txt
RUN pip install --no-cache-dir -r /simulator/requirements.txt

# If you need Playwright in the simulator worker, uncomment the following line:
# RUN playwright install --with-deps

COPY . /simulator

ENV PYTHONUNBUFFERED=1

# Default command: run the simulator worker which processes jobs from Redis
CMD ["python", "worker.py"]