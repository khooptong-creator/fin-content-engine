# Fin-Content Engine worker — Railway/Fly deploy image.
# Python 3.12 (pyproject requires >=3.11; 3.12 is the stable choice — 3.14 is
# bleeding-edge and some deps lag). Single always-on process: FastAPI + APScheduler.

FROM python:3.12-slim

# Playwright is needed in P4 (IG carousel rendering) but is harmless to install
# now and avoids a base-image change later. Skip the browser binaries for now
# (saves ~500MB); uncomment the install line in P4.
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
#     libcups2 libdrm2 libdbus-1-3 libxkbcommon0 libx11-6 libxcomposite1 \
#     libxdamage1 libxext6 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 \
#     libcairo2 libasound2 \
#  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (better layer caching).
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e .

# Copy the worker code.
COPY app/ ./app/
COPY scripts/ ./scripts/

# Railway injects env vars at runtime. The worker reads FCE_* via pydantic-settings.
ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# uvicorn serves the FastAPI app; APScheduler runs in-process via lifespan hooks.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
