# Database

The initial and second migrations are in `backend/core/migrations/`. UUIDs identify users, conversations and messages. Uniqueness constraints cover participant membership, per sender client message keys, reactions, story views, template locale, and webhook payload digests.

```mermaid
erDiagram
  User ||--o{ Contact : owns
  User ||--o{ Participant : joins
  Conversation ||--o{ Participant : contains
  Conversation ||--o{ Message : stores
  Message ||--o{ MessageReceipt : tracks
  Message ||--o{ Attachment : has
  Message ||--o{ Reaction : has
  User ||--o{ Story : posts
  Story ||--o{ StoryView : receives
  User ||--o{ WhatsAppBusinessAccount : owns
  Message ||--o| OutboundJob : queues
```

Conversation activity and message creation times are indexed. WebhookEvent holds the signed webhook body after validation for retry. The account access token is never stored in the database.
