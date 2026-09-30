FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDHUB_HOST=0.0.0.0 \
    MEDHUB_PORT=8000

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 prime \
    && useradd --uid 10001 --gid prime --no-create-home prime \
    && mkdir /app/data \
    && chown prime:prime /app/data

# Explicit allowlist prevents .env, Git history and local patient/demo data entering the image.
COPY --chown=prime:prime server.py config.py domain.py assistant_logic.py agent_engine.py agent_prompts.py metrics.py ./
COPY --chown=prime:prime public ./public

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=2)" || exit 1
CMD ["python", "server.py"]
