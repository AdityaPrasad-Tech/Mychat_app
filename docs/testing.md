# Testing

Backend: `cd backend && .venv/Scripts/pytest -q` on Windows, or `pytest -q` inside the backend container. Tests cover registration/login and CSRF, contact isolation, internal message idempotency and permissions, session backed WebSocket tokens, JSON safe live events, WebSocket subscription authorization, group admin rules, story expiration, attachment privacy, webhook signature and deduplication, and WhatsApp window policy and out-of-order statuses.

Frontend: `cd frontend && npm run typecheck && npm run lint && npm run build`. With Docker Compose running and Chrome installed, `npm run test:e2e` runs two browser flows for direct friend messaging, groups, status and settings.

Compose: `docker compose config --quiet`, then `docker compose up --build -d` and check `http://localhost:3100/login/`, `http://localhost:3100/api/docs/` and `http://localhost:8000/health/`.

Not yet present: Vitest/React Testing Library component tests, broad browser accessibility and E2E coverage, load tests, Meta sandbox integration tests, media malware tests, GCP smoke tests.
