# Security notes

- Session cookies are HttpOnly and Secure outside debug mode. Registration and login are CSRF protected; the webhook uses HMAC instead.
- Every conversation, message, attachment and story read checks membership or visibility on the server.
- File downloads require a session and pass through Django. The file system volume is private and object names are randomized.
- Message bodies are rendered as React text. No HTML from messages is injected.
- Production requires `DJANGO_SECRET_KEY`, HTTPS, correct hosts/origins, private object storage, file inspection, network policy, backups, and an independent security review.
- Server stored messages are not end to end encrypted.

Remaining risks: no account recovery or MFA, limited login rate controls, no malware scan, no token rotation automation, and incomplete WhatsApp operations. The local Compose credentials are development values and must never be reused.
