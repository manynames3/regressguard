FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.8.13
COPY pyproject.toml uv.lock ./
COPY regressguard regressguard
COPY api api
COPY demo demo
RUN uv sync --locked --no-dev
COPY prompts prompts
COPY suites suites
COPY baselines baselines
RUN useradd --create-home app && mkdir -p /app/data && chown -R app:app /app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s CMD ["/app/.venv/bin/python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz', timeout=2)"]
CMD ["/app/.venv/bin/uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
