# API

Versioned endpoints live under `/api/v1/`. Interactive OpenAPI documentation is at `/api/docs/` and the schema at `/api/schema/`.

Authentication uses a Django session cookie. Fetch `GET /api/v1/auth/csrf/` first; send its `csrfToken` as `X-CSRFToken` on writes. Local Compose routes the site, API and WebSocket through the gateway on port 3100.

Implemented groups:

| Resource | Endpoints |
| --- | --- |
| Auth | `auth/csrf/`, `auth/register/`, `auth/login/`, `auth/logout/`, `auth/me/`, `auth/websocket-token/` |
| Profile | `users/me/`, `users/me/preferences/` |
| Contacts | `contacts/`, `contacts/{id}/` |
| Chats | `conversations/`, `conversations/{id}/`, `conversations/{id}/messages/`, `conversations/{id}/{archive,mute,pin,read}/` |
| Messages | `messages/{id}/`, `messages/{id}/reactions/`, `conversations/{id}/attachments/`, `attachments/{id}/download/` |
| Groups | `groups/`, `groups/{id}/`, `groups/{id}/members/`, `groups/{id}/members/{userId}/` |
| Stories | `stories/`, `stories/{id}/`, `stories/{id}/view/`, `stories/{id}/media/` |
| WhatsApp | `integrations/whatsapp/status/`, `integrations/whatsapp/templates/`, `integrations/whatsapp/messages/`, `webhooks/whatsapp/` |

`POST /conversations/{id}/messages/` requires `body` and a `client_message_id` UUID. Retrying with the same key returns the existing message. `GET /conversations/{id}/messages/` returns at most 50 messages and `has_more`. To load older messages, pass the oldest displayed message's ISO timestamp as `before` and UUID as `before_id`; both fields keep paging stable when messages share a timestamp.

WebSocket endpoint: `/ws/chat/`. An authenticated client fetches `GET /auth/websocket-token/`, then connects to `/ws/chat/?token={token}` on the same browser origin. The token expires after 90 seconds and requires a live login session when used to connect. After connection send `{"event":"subscribe","conversation_id":"uuid"}`. Server events include `message.created`, `message.updated`, `message.deleted`, `message.status_changed`, `conversation.read`, and typing updates. REST remains authoritative after reconnect.
