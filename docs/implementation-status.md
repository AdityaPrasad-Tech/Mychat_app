# Implementation status

Updated 2026-10-16. This file is the source of truth for the current milestone; do not describe the entire master prompt as complete.

## Working milestone

- [x] Next.js App Router, strict TypeScript, Tailwind design tokens, responsive light and dark layout.
- [x] Session login, registration, logout, profile and preferences APIs.
- [x] Contacts CRUD, favorites and blocking controls, E.164 validation, registered user linking by email (including registration after a contact is saved).
- [x] Internal one to one and group conversations, membership checks, text messages, idempotency keys, edit, delete, reactions, read and delivery receipts.
- [x] Authenticated Channels WebSocket subscriptions using short lived session tokens, visible typing state, message notifications, reconnect and REST history resync. Removed group members stop receiving events.
- [x] Internal attachments with inline image, audio and video previews, plus 24 hour stories with private download endpoints.
- [x] Group name, member add/remove and leave controls with automatic admin succession. The Compose gateway serves the site, API and WebSocket on host port 3100, with trusted LAN host configuration through environment values.
- [x] Official WhatsApp text and approved template queue, signed webhook inbox, inbound text, status updates, policy window and opt-in checks. Live Meta test not yet run.
- [x] PostgreSQL migrations, Redis, Celery worker and scheduler, Docker Compose, seed command, OpenAPI, backend tests, and browser tests of direct chat and main controls.

## Incomplete or limited

- [ ] Email verification, password reset, MFA, session inventory, account export/deletion.
- [ ] Contact import, tags, group role changes, pinned messages.
- [ ] Message search, virtualized lists, offline drafts, richer presence and background notification delivery. The UI now pages older messages and supports basic browser alerts while open in a background tab.
- [ ] Browser story viewer progress, pause/resume and advanced privacy selection.
- [ ] Cloud object storage, signed upload URLs, malware scanning, image processing and validated media transcoding. Local media uses an authenticated Django download route.
- [ ] WhatsApp media receive/download/send, interactive messages, template chooser UI and synchronization, rate limit and cost accounting, provider reconciliation after ambiguous timeout, dead-letter tooling.
- [ ] Full production GCP deployment, monitoring, backups, CI/CD, load tests, broader browser coverage and security audit.
- [ ] Admin privacy tooling and per-organization isolation. Current WhatsApp mapping is one business number per owner.

## External verification

No Meta credentials or verified recipient were supplied. A real Cloud API send and incoming webhook cannot be demonstrated here. Production infrastructure was not created.

## Verified locally

- `docker compose up --build -d` starts PostgreSQL, Redis, backend, frontend, gateway, worker and scheduler; the backend, frontend and gateway health checks pass. MinIO remains an unused optional profile.
- The gateway returned HTTP 200 from the site and Django's CSRF endpoint through both localhost and the host LAN address.
- The seeded Alice account sent a `[DEMO]` message through the API; Bob retrieved it from PostgreSQL and marked the conversation read.
- 14 backend tests passed. Two Chrome browser flows passed through the LAN address, covering two way text and image chat, live typing, edits, deletion, contact and group controls, status and settings. Ruff, TypeScript, ESLint, Compose config and the Docker frontend production build passed.

## Next implementation steps

1. Finish account recovery and email verification, plus session controls.
2. Add durable media storage and file inspection before broadening upload support.
3. Complete WhatsApp media and template synchronization against the target Graph API version and a Meta test number.
4. Expand browser E2E coverage and prepare a deployment architecture suited to long running workers.
