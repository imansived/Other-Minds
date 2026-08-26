# The Streamlit client: conversation + divergence pages.
#
# A separate process from the API, talking to it over HTTP exactly as it does
# locally. It imports nothing from backend/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY ui/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ui ./ui
# The agent portraits. streamlit_app.py resolves them relative to the repo
# root, and degrades to no avatar when they are absent — so without this the
# app still runs and simply looks wrong, which is worth avoiding.
COPY public/minds ./public/minds

RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8501

# --server.address is passed here rather than left to .streamlit/config.toml.
# That file deliberately pins 127.0.0.1 so a local run is not exposed to the
# network, but inside a container the loopback is the container's own and
# nothing could reach it. A CLI flag overrides the config file.
CMD ["streamlit", "run", "ui/main.py", \
     "--server.address=0.0.0.0", \
     "--server.port=8501", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]

HEALTHCHECK --interval=15s --timeout=5s --start-period=25s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"
