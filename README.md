# MyChat

MyChat is a full stack messaging application under active development. It has a Next.js client, Django REST API, PostgreSQL persistence, Redis backed Channels WebSockets, Celery jobs, and a guarded WhatsApp Business Cloud API adapter. See [implementation status](docs/implementation-status.md) before treating any feature as production ready.

## Run locally

Requirements: Docker Desktop with Compose. Run these commands from the project directory.

```powershell
docker compose up --build -d
docker compose exec backend python manage.py seed_demo
```

Open http://localhost:3100. The frontend runs on port 3000 inside its container. A local gateway publishes the site, API and live chat together on host port 3100; MyChat does not use host ports 3000 or 3001. Demo accounts are `alice@example.test`, `bob@example.test`, and `charlie@example.test`, each with password `DemoPass123!`. Demo messages are labeled `[DEMO]`. These accounts are for local development only.

## Chat with another account

1. Both people create accounts on **the same MyChat server**. A Gmail address can be used as the account email, but Google login is not connected.
2. Sign in at http://localhost:3100 and open **Contacts → Add contact**. Enter your friend's name and the exact email they registered with, then save.
3. Open the saved contact and select **Start MyChat conversation**. If the contact says **Not linked yet**, ask your friend to register on this server and select **Check again**.
4. Send a message. Your friend will see the new chat within about five seconds and can reply. Try Alice and Bob in separate browser profiles or an incognito window to test without another person.

If your existing local account reports an invalid password, reset that account's password from this project's terminal with `docker compose exec backend python manage.py changepassword your-email@example.com`, then sign in again at port 3100. This keeps the account and its chats. Email based password reset is not set up yet.

### Chat on another device on the same Wi-Fi or trusted LAN

Find this computer's LAN IPv4 address with `Get-NetIPAddress -AddressFamily IPv4`. Edit the project's `.env` file (copy `.env.example` if needed) and include that address in both `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`. For example, if the address is `192.168.1.50`:

```dotenv
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,backend,192.168.1.50
CSRF_TRUSTED_ORIGINS=http://localhost:3100,http://localhost:8000,http://192.168.1.50:3100
```

Run `docker compose up --build -d` again. On the other device, open `http://192.168.1.50:3100`, create a second account, then add each other by registered email. Both devices must be on the same trusted network, and the computer's firewall must allow inbound TCP 3100. The site, API and live chat all use that port. If the LAN address changes, update `.env` and restart Compose. Microphone recording and browser notifications may require HTTPS on other devices; text and file chat work over this local HTTP setup.

Friends outside your network need a reachable HTTPS deployment. This development Compose setup is not prepared for public exposure.

To check the running services or stop MyChat without deleting its saved database:

```powershell
docker compose ps
docker compose down
```

API health: http://localhost:8000/health/  
OpenAPI UI: http://localhost:3100/api/docs/

The local backend uses a private Docker volume for media. An optional `minio` profile is defined, but it is not connected to the application and its image could not be pulled in this environment. WhatsApp remains disconnected until official Meta credentials and an account mapping are configured.

Migrations normally run as the backend container starts. To run them manually:

```bash
docker compose exec backend python manage.py migrate
```

Run checks:

```powershell
docker compose exec backend pytest -q
docker compose exec backend python manage.py check
cd frontend
npm ci
npm run typecheck
npm run lint
npm run build
npm run test:e2e
```

The browser test uses an installed Google Chrome and the running Docker app at http://localhost:3100.

## Development without Docker

Python 3.12 and Node 22 are supported. Copy `.env.example` values into your shell, install `backend/requirements.txt`, run migrations, then start Daphne. The backend defaults to SQLite if `DATABASE_URL` is unset, but Redis is still required for WebSockets and Celery. From `frontend`, run `npm ci`, set `NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws/chat/`, then run `npm run dev -- -p 3100`; the Next.js rewrite sends `/api/` requests to `http://localhost:8000`.

## Security and scope

MyChat account login uses Django session cookies and CSRF protection. Never commit real secrets. Use HTTPS, external secret storage, private media storage, and a deployment review before exposing this service publicly. MyChat stores message content on its servers; it does not claim end to end encryption. WhatsApp integration uses only the official Business Cloud API and does not provide personal WhatsApp history or Status.

Documentation: [architecture](docs/architecture.md), [API](docs/api.md), [database](docs/database.md), [WhatsApp](docs/whatsapp-integration.md), [security](docs/security.md), [deployment](docs/deployment.md), [testing](docs/testing.md).
