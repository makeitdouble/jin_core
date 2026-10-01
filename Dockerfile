FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY . .

# These paths contain runtime state and are normally bind-mounted by Compose.
RUN mkdir -p \
    /app/memory \
    /app/logs \
    /app/logs_anon \
    /app/assets/files \
    /app/assets/outputs

ENV JIN_HOST=0.0.0.0 \
    JIN_PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=2)"

CMD ["python", "app.py"]
