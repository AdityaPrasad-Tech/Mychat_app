import hashlib
import hmac
from datetime import datetime, timedelta, timezone as datetime_timezone
import httpx
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from .models import Conversation, Message, OutboundJob, Participant, PendingProviderStatus, WebhookEvent, WhatsAppBusinessAccount, WhatsAppContact
from .realtime import broadcast
from .serializers import MessageSerializer


TEMPLATE_REQUIRED = "This conversation requires an approved WhatsApp message template before you can send a new message."
STATUS_RANK = {"pending": 0, "queued": 1, "sent": 2, "delivered": 3, "read": 4}


def configured():
    return all((settings.WHATSAPP_ACCESS_TOKEN, settings.WHATSAPP_PHONE_NUMBER_ID, settings.WHATSAPP_APP_SECRET, settings.WHATSAPP_VERIFY_TOKEN))


def check_signature(raw, header):
    if not settings.WHATSAPP_APP_SECRET or not header.startswith("sha256="):
        return False
    expected = hmac.new(settings.WHATSAPP_APP_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header[7:], expected)


def graph_post(payload):
    url = f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    with httpx.Client(timeout=15) as client:
        response = client.post(url, json={"messaging_product": "whatsapp", **payload},
                               headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"})
        response.raise_for_status()
        return response.json()


def validate_outbound(account, phone, message_type, template=None):
    if not configured() or not account.is_active or account.phone_number_id != settings.WHATSAPP_PHONE_NUMBER_ID:
        raise ValidationError({"code": "WHATSAPP_DISCONNECTED", "message": "WhatsApp Business is disconnected."})
    contact = WhatsAppContact.objects.filter(account=account, phone_number=phone).first()
    if message_type == "template":
        if not contact or not contact.opted_in_at:
            raise ValidationError({"code": "WHATSAPP_OPT_IN_REQUIRED", "message": "Recipient opt-in is required."})
        if not template or template.status != "approved" or template.account_id != account.id:
            raise ValidationError({"code": "WHATSAPP_TEMPLATE_INVALID", "message": "Choose an approved template."})
    elif not contact or not contact.last_inbound_at or contact.last_inbound_at < timezone.now() - timedelta(hours=24):
        raise ValidationError({"code": "WHATSAPP_TEMPLATE_REQUIRED", "message": TEMPLATE_REQUIRED})


@transaction.atomic
def queue_message(owner, conversation, body="", message_type="text", template=None, client_message_id=None):
    account = WhatsAppBusinessAccount.objects.filter(owner=owner, phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID).first()
    if not account or conversation.channel_type != "whatsapp" or not conversation.remote_phone:
        raise ValidationError({"code": "WHATSAPP_CONVERSATION_INVALID", "message": "WhatsApp conversation is unavailable."})
    if client_message_id:
        existing = Message.objects.filter(sender=owner, client_message_id=client_message_id).first()
        if existing:
            if existing.conversation_id != conversation.id:
                raise ValidationError({"client_message_id": "Already used in another conversation."})
            return existing
    validate_outbound(account, conversation.remote_phone, message_type, template)
    if message_type == "text" and (not body.strip() or len(body) > 4096):
        raise ValidationError({"body": "Enter 1 to 4096 characters."})
    try:
        with transaction.atomic():
            message = Message.objects.create(conversation=conversation, sender=owner, provider="whatsapp", body=template.name if template else body,
                                             message_type=message_type, client_message_id=client_message_id, status="queued")
    except IntegrityError:
        return Message.objects.get(sender=owner, client_message_id=client_message_id)
    payload = {"to": conversation.remote_phone, "type": message_type}
    if message_type == "text":
        payload["text"] = {"body": body}
    else:
        payload["template"] = {"name": template.name, "language": {"code": template.language}}
    OutboundJob.objects.create(message=message, payload=payload)
    conversation.last_activity_at = timezone.now()
    conversation.save(update_fields=["last_activity_at"])
    return message


def process_webhook_event(event_id):
    event = WebhookEvent.objects.get(pk=event_id)
    if event.processed_at:
        return
    try:
        for entry in event.payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_id = value.get("metadata", {}).get("phone_number_id")
                account = WhatsAppBusinessAccount.objects.filter(phone_number_id=phone_id, is_active=True).first()
                if not account:
                    continue
                account.last_webhook_at = timezone.now()
                account.save(update_fields=["last_webhook_at"])
                for item in value.get("messages", []):
                    ingest_message(account, item, value.get("contacts", []))
                for item in value.get("statuses", []):
                    ingest_status(item)
        event.processed_at = timezone.now()
        event.error = ""
        event.save(update_fields=["processed_at", "error"])
    except Exception as exc:
        event.error = str(exc)[:255]
        event.save(update_fields=["error"])
        raise


@transaction.atomic
def ingest_message(account, item, contacts):
    provider_id = item.get("id")
    remote = item.get("from")
    if not provider_id or not remote or Message.objects.filter(provider_message_id=provider_id).exists():
        return
    profile = next((c.get("profile", {}) for c in contacts if c.get("wa_id") == remote), {})
    contact, _ = WhatsAppContact.objects.get_or_create(account=account, phone_number=remote)
    contact.name = str(profile.get("name", contact.name))[:100]
    try:
        inbound_at = datetime.fromtimestamp(int(item["timestamp"]), tz=datetime_timezone.utc)
    except (KeyError, ValueError, TypeError, OverflowError):
        inbound_at = timezone.now()
    inbound_at = min(inbound_at, timezone.now())
    contact.last_inbound_at = max(filter(None, (contact.last_inbound_at, inbound_at)))
    contact.save(update_fields=["name", "last_inbound_at"])
    conversation = Conversation.objects.filter(channel_type="whatsapp", remote_phone=remote, created_by=account.owner).first()
    if not conversation:
        conversation = Conversation.objects.create(channel_type="whatsapp", remote_phone=remote,
                                                   title=contact.name or remote, created_by=account.owner)
        Participant.objects.create(conversation=conversation, user=account.owner, role="admin")
    kind = item.get("type", "text")
    body = item.get("text", {}).get("body", "") if kind == "text" else f"[{kind} attachment]"
    message = Message.objects.create(conversation=conversation, external_sender_id=remote, provider="whatsapp",
                                     provider_message_id=provider_id, message_type=kind if kind in dict(Message.TYPES) else "text",
                                     body=body[:4096], status="delivered", delivered_at=timezone.now())
    conversation.last_activity_at = message.created_at
    conversation.save(update_fields=["last_activity_at"])
    broadcast(conversation.id, {"event": "message.created", "conversation_id": str(conversation.id), "message": MessageSerializer(message).data})


def ingest_status(item):
    message = Message.objects.filter(provider_message_id=item.get("id")).first()
    if not message:
        if item.get("id") and item.get("status") in ("sent", "delivered", "read", "failed"):
            PendingProviderStatus.objects.get_or_create(provider_message_id=item["id"], status=item["status"], defaults={"payload": item})
        return
    provider_status = item.get("status")
    if provider_status == "failed":
        if message.status in ("delivered", "read"):
            return
        message.status = "failed"
        message.error_code = str((item.get("errors") or [{}])[0].get("code", "provider_failed"))[:80]
        message.save(update_fields=["status", "error_code"])
    elif provider_status in STATUS_RANK and STATUS_RANK[provider_status] > STATUS_RANK.get(message.status, -1):
        message.status = provider_status
        timestamp = timezone.now()
        if provider_status == "sent":
            message.sent_at = timestamp
        elif provider_status == "delivered":
            message.delivered_at = timestamp
        elif provider_status == "read":
            message.read_at = timestamp
        message.save()
    else:
        return
    broadcast(message.conversation_id, {"event": "message.status_changed", "conversation_id": str(message.conversation_id), "message": MessageSerializer(message).data})


def apply_pending_status(provider_message_id):
    items = PendingProviderStatus.objects.filter(provider_message_id=provider_message_id).order_by("created_at")
    for pending in items:
        ingest_status(pending.payload)
        pending.delete()
