FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ /app/backend/

ARG FRONTEND_BUST=1
COPY frontend/ /app/frontend/

ENV FRONTEND_DIR=/app/frontend

WORKDIR /app/backend

EXPOSE ${PORT:-8001}

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8001}
