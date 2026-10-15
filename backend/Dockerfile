FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       default-libmysqlclient-dev \
       pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

# 唯讀 Django admin 的靜態檔（CSS/JS）：建置時收集，由 Nginx 提供（見 frontend/Dockerfile）。
# collectstatic 不連資料庫，settings 需要的密碼檔在建置時用假的。
RUN echo build-only > /tmp/build_secret \
    && DJANGO_SECRET_KEY_FILE=/tmp/build_secret MYSQL_PASSWORD_FILE=/tmp/build_secret \
       python manage.py collectstatic --noinput \
    && rm /tmp/build_secret

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app \
    && mkdir -p /data/documents \
    && chown 1001:1001 /data/documents \
    && chmod 750 /data/documents
# ↑ 案件文件的 volume 掛載點。compose 以 1001:1001 執行（見 compose.yaml 的 user）；
#   新建立的 named volume 會沿用這個目錄的擁有者與權限。

USER appuser

# 2026-10-15 壓力測試（qa/stress/RESULTS-20261015.md）：2 個 worker 時，有人開 Accounting（23 秒）其他人全部排隊；
# 4 個 worker（= CPU 核心數）後一般操作不再被卡住。不要用 --threads：多個 Accounting 同時在記憶體裡會撐爆記憶體。
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "4", "--timeout", "60", "ri_system.wsgi:application"]
