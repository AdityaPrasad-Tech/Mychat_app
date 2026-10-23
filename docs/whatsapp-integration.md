# WhatsApp Business integration

The adapter calls the official Meta Graph API `/messages` endpoint through `httpx`. Use the current version applicable to your Meta app via `META_GRAPH_API_VERSION`; validate the schemas again during production onboarding. The implementation currently supports text and approved template sends only.

Configure `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_APP_SECRET`, and `WHATSAPP_VERIFY_TOKEN` as runtime secrets. In Django Admin, add a `WhatsAppBusinessAccount` for the owner with the same phone number ID. The webhook callback is `/api/v1/webhooks/whatsapp/`. A production callback requires HTTPS.

GET verifies the challenge token. POST verifies `X-Hub-Signature-256` against the raw body and rejects invalid signatures. It stores each unique payload before queuing processing. The scheduler retries unprocessed events. Inbound text and status updates are idempotent by provider message ID. A free-form outbound text requires an inbound customer message within the previous 24 hours. Template sends require a stored approved template and explicit opt-in date. Meta policy and account configuration remain authoritative.

Known limitations: no live Meta test has run, no inbound media download, no template synchronization, no template component parameters, no cost reporting, and no automated reconciliation for ambiguous API timeouts. A timeout leaves an `uncertain` outbox job for manual investigation. Do not repeatedly retry it without checking Meta.

Official sources used for the supported `/messages` endpoint and types: [Meta's WhatsApp Business Platform API collection](https://www.postman.com/meta/whatsapp-business-platform/folder/13382743-ba8d099d-007e-4b52-b9f2-3cf3c60e4fbc), [WhatsApp Business developer hub](https://whatsappbusiness.com/developers/developer-hub/).
