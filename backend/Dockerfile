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
    && chown -R appuser:appuser /app

USER appuser

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "2", "--timeout", "60", "ri_system.wsgi:application"]
