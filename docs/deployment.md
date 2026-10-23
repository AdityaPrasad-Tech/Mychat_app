# Deployment plan

Local Compose is validated separately from production. No billable GCP resources are created by this repository.

Recommended production layout: Next.js and Daphne on separate Cloud Run services, Cloud SQL PostgreSQL, Memorystore Redis for Channels, private Cloud Storage for media, Secret Manager for keys, Artifact Registry for images, and Cloud Logging/Monitoring. Apply migrations as a one-off release job before routing traffic. Run the Celery worker and beat on a dedicated long running compute service or replace them with Cloud Tasks and Cloud Run Jobs; a scale-to-zero HTTP Cloud Run service is not a permanent worker.

Cloud Run WebSockets can disconnect at request timeout or instance replacement. The client reconnects and reloads history from PostgreSQL. Set a deliberate connection timeout and size Redis for the expected number of active subscriptions.

Production deployment is **not configured or validated yet**. Before deployment, add Cloud Storage integration, secret injection, worker hosting, backup/restore checks, monitoring alerts, load tests, an external HTTPS domain, and a rollback procedure that accounts for schema changes. Keep at least one prior container image; roll back application images only if the migrated schema remains compatible. Restore Cloud SQL from a tested backup for irreversible data errors.
