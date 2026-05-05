FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SAGAQUILL_HOST=0.0.0.0
ENV SAGAQUILL_PORT=8765
ENV SAGAQUILL_CONTINUATION_MODE=hybrid

WORKDIR /app

COPY pyproject.toml README.md ./
COPY sagaquill ./sagaquill
COPY examples ./examples

RUN pip install --no-cache-dir .

RUN mkdir -p /app/runs /app/.sagaquill

VOLUME ["/app/runs", "/app/.sagaquill"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('SAGAQUILL_PORT', '8765'), timeout=3).close()" || exit 1

CMD ["sh", "-c", "sagaquill serve --host \"${SAGAQUILL_HOST}\" --port \"${SAGAQUILL_PORT}\""]
