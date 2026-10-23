import httpx
from celery import shared_task
from django.db import transaction
from django.utils import timezone
from .models import OutboundJob, PendingProviderStatus, Story, WebhookEvent
from .whatsapp import apply_pending_status, graph_post, process_webhook_event


@shared_task
def process_whatsapp_event(event_id):
    process_webhook_event(event_id)


@shared_task
def dispatch_outbox():
    for job in OutboundJob.objects.filter(state="queued", next_attempt_at__lte=timezone.now()).select_related("message__conversation")[:50]:
        send_whatsapp_job.delay(str(job.id))


@shared_task
def send_whatsapp_job(job_id):
    with transaction.atomic():
        job = OutboundJob.objects.select_for_update().select_related("message__conversation").get(pk=job_id)
        if job.state != "queued":
            return
        job.state = "sending"
        job.attempts += 1
        job.save(update_fields=["state", "attempts"])
    message = job.message
    try:
        result = graph_post(job.payload)
        message.provider_message_id = result["messages"][0]["id"]
        message.status = "sent"
        message.sent_at = timezone.now()
        message.save(update_fields=["provider_message_id", "status", "sent_at"])
        apply_pending_status(message.provider_message_id)
        job.state = "sent"
        job.save(update_fields=["state"])
    except (httpx.TimeoutException, httpx.TransportError):
        # Acceptance is ambiguous after transport failure. A human must reconcile before another send.
        job.state = "uncertain"
        job.last_error = "Transport outcome uncertain; inspect Meta before retrying."
        job.save(update_fields=["state", "last_error"])
    except Exception as exc:
        job.state = "failed"
        job.last_error = str(exc)[:255]
        job.save(update_fields=["state", "last_error"])
        message.status = "failed"
        message.error_message = "Provider rejected this send."
        message.save(update_fields=["status", "error_message"])


@shared_task
def expire_stories():
    expired = Story.objects.filter(expires_at__lte=timezone.now())
    for story in expired.iterator():
        if story.media:
            story.media.delete(save=False)
        story.delete()
    WebhookEvent.objects.filter(processed_at__lt=timezone.now() - timezone.timedelta(days=30)).delete()
    PendingProviderStatus.objects.filter(created_at__lt=timezone.now() - timezone.timedelta(days=30)).delete()


@shared_task
def retry_webhook_events():
    for event in WebhookEvent.objects.filter(processed_at__isnull=True).order_by("created_at")[:50]:
        process_whatsapp_event.delay(str(event.id))
