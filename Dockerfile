FROM node:22-bookworm-slim AS web
WORKDIR /build
RUN corepack enable && corepack prepare pnpm@11.25.0 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY requirements.txt requirements-lock.txt ./
RUN pip install --no-cache-dir -r requirements.txt -c requirements-lock.txt && useradd --create-home --uid 10001 kurai
COPY backend ./backend
COPY migrations ./migrations
COPY alembic.ini .
COPY data ./data
COPY --from=web /build/dist ./frontend/dist
USER kurai
EXPOSE 8000
CMD ["sh", "-c", "python -m alembic upgrade head && python -m kurai.seed && uvicorn kurai.main:app --host 0.0.0.0 --port 8000 --no-access-log"]
