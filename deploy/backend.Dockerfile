FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY backend /app/backend
RUN pip install --no-cache-dir --upgrade pip==26.2.0 && pip install --no-cache-dir ./backend && useradd --uid 10001 --create-home ares \
    && mkdir /data && chown ares:ares /data
USER ares
CMD ["python", "-m", "uvicorn", "ares.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
