FROM python:3.12-slim

# System dependencies required by Playwright/Chromium
RUN apt-get update && apt-get install -y \
    libnss3 libnspr4 libdbus-1-3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 \
    libcairo2 libatspi2.0-0 libwayland-client0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install chromium

COPY *.py ./

# /data is mounted as a persistent volume — cache, raw_html, and CSVs live here
RUN mkdir -p /data

# Run from /data so all relative file paths resolve to the persistent volume
CMD ["sh", "-c", "cd /data && python /app/run.py && python /app/digest.py"]
