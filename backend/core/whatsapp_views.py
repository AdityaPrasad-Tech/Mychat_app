import hashlib
import json
import uuid
from django.conf import settings
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import WebhookEvent, WhatsAppBusinessAccount, WhatsAppTemplate
from .serializers import MessageSerializer
from .views import get_conversation
from .whatsapp import check_signature, configured, queue_message


class WhatsAppStatusView(APIView):
    def get(self, request):
        account = WhatsAppBusinessAccount.objects.filter(owner=request.user, phone_number_id=settings.WHATSAPP_PHONE_NUMBER_ID).first()
        return Response({"configured": bool(configured() and account and account.is_active),
                         "connection_state": "configured_unverified" if configured() and account and account.is_active else "disconnected",
                         "phone_number": account.display_phone_number if account else "",
                         "phone_number_id": account.phone_number_id if account else "",
                         "business_account_id": account.waba_id if account else "",
                         "last_webhook_at": account.last_webhook_at if account else None})


class WhatsAppTemplatesView(APIView):
    def get(self, request):
        if not request.user.whatsapp_accounts.exists():
            return Response([])
        return Response(list(WhatsAppTemplate.objects.filter(account__owner=request.user, status="approved").values("id", "name", "language", "status", "category")))


class WhatsAppSendView(APIView):
    def post(self, request):
        try:
            conversation_id = uuid.UUID(str(request.data.get("conversation_id")))
        except (ValueError, TypeError):
            raise ValidationError({"conversation_id": "A UUID is required."})
        conversation = get_conversation(request, conversation_id)
        try:
            client_id = uuid.UUID(str(request.data.get("client_message_id")))
        except (ValueError, TypeError):
            raise ValidationError({"client_message_id": "A UUID is required."})
        kind = request.data.get("type", "text")
        if kind not in ("text", "template"):
            raise ValidationError({"type": "This message type is unavailable."})
        template = None
        if kind == "template":
            try:
                template_id = uuid.UUID(str(request.data.get("template_id")))
            except (ValueError, TypeError):
                raise ValidationError({"template_id": "An approved template is required."})
            template = WhatsAppTemplate.objects.filter(pk=template_id, account__owner=request.user, status="approved").first()
        message = queue_message(request.user, conversation, body=str(request.data.get("body", "")),
                                message_type=kind, template=template, client_message_id=client_id)
        return Response(MessageSerializer(message).data, status=202)


@method_decorator(csrf_exempt, name="dispatch")
class WhatsAppWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        if request.query_params.get("hub.mode") == "subscribe" and settings.WHATSAPP_VERIFY_TOKEN and request.query_params.get("hub.verify_token") == settings.WHATSAPP_VERIFY_TOKEN:
            return HttpResponse(request.query_params.get("hub.challenge", ""), content_type="text/plain")
        return Response({"detail": "Verification failed."}, status=403)

    def post(self, request):
        raw = request.body
        if not check_signature(raw, request.headers.get("X-Hub-Signature-256", "")):
            return Response({"detail": "Invalid signature."}, status=403)
        if len(raw) > 1024 * 1024:
            return Response({"detail": "Payload too large."}, status=413)
        try:
            payload = json.loads(raw)
        except ValueError:
            return Response({"detail": "Invalid JSON."}, status=400)
        if payload.get("object") != "whatsapp_business_account" or not isinstance(payload.get("entry"), list):
            return Response({"detail": "Invalid event."}, status=400)
        identity = hashlib.sha256(raw).hexdigest()
        event, created = WebhookEvent.objects.get_or_create(identity=identity, defaults={"payload": payload})
        if created:
            from .tasks import process_whatsapp_event
            try:
                process_whatsapp_event.delay(str(event.id))
            except Exception:
                # The database inbox remains durable; the scheduler will dispatch it.
                pass
        return Response({"accepted": True}, status=200)
