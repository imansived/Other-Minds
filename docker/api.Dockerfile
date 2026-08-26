# The FastAPI service: agents, prompts, turn logic, storage, analytics.
#
# Build context is the repo root, so this can copy backend/ without reaching
# outside its own directory.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so editing a prompt or a route does not reinstall pandas.
COPY backend/requirements.txt backend/requirements-analytics.txt ./
# requirements-analytics.txt pulls in requirements.txt as well as pandas /
# numpy / scikit-learn. The analytics are installed because the Streamlit UI's
# Divergence page depends on /analytics/divergence; for a serving-only image,
# swap this for requirements.txt and the endpoint answers 501 rather than
# breaking anything else.
RUN pip install --no-cache-dir -r requirements-analytics.txt

COPY backend/app ./app

# The SQLite database lives on a volume so conversations and the corpus survive
# a rebuild. DB_PATH is absolute, so store.py does not resolve it against
# /app.
ENV DB_PATH=/data/other_minds.db
RUN mkdir -p /data

# Run as a non-root user, which also needs to own the data directory.
RUN useradd --create-home --uid 10001 app && chown -R app:app /data /app
USER app

EXPOSE 8000

# 0.0.0.0 inside the container, NOT the 127.0.0.1 used locally: the loopback
# here is the container's own, and binding it would make the service
# unreachable from the compose network. Exposure is controlled by which ports
# compose publishes.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
