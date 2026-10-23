import uuid
import mimetypes
from datetime import timedelta
from PIL import Image, UnidentifiedImageError
from django.contrib.auth import authenticate, login, logout
from django.core import signing
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import FileResponse, Http404
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from .models import Attachment, Contact, Conversation, Message, MessageReceipt, Participant, Preference, Reaction, Story, StoryView, User
from .realtime import broadcast
from .serializers import ContactSerializer, ConversationSerializer, MessageSerializer, PreferenceSerializer, RegisterSerializer, StorySerializer, UserSerializer


SAFE_EXTENSIONS = {"image/jpeg": "jpg", "image/png": "png", "image/gif": "gif", "image/webp": "webp",
                   "video/mp4": "mp4", "video/webm": "webm", "audio/webm": "webm", "audio/ogg": "ogg",
                   "audio/mpeg": "mp3", "audio/mp4": "m4a", "application/pdf": "pdf", "text/plain": "txt"}


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["GET"])
@permission_classes([AllowAny])
def csrf(request):
    return Response({"csrfToken": get_token(request)})


@method_decorator(csrf_protect, name="dispatch")
class RegisterView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "register"

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        Contact.objects.filter(email__iexact=user.email, linked_user__isnull=True).exclude(owner=user).update(linked_user=user)
        login(request, user)
        return Response(UserSerializer(user).data, status=201)


@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def post(self, request):
        user = authenticate(request, username=request.data.get("email", "").lower(), password=request.data.get("password", ""))
        if not user:
            return Response({"detail": "Invalid email or password."}, status=400)
        login(request, user)
        return Response(UserSerializer(user).data)


class LogoutView(APIView):
    def post(self, request):
        logout(request)
        return Response(status=204)


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

    def patch(self, request):
        serializer = UserSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class WebSocketTokenView(APIView):
    def get(self, request):
        token = signing.dumps({"user_id": str(request.user.id), "session_key": request.session.session_key}, salt="mychat-websocket")
        return Response({"token": token})


class PreferenceView(APIView):
    def get_object(self, request):
        return Preference.objects.get_or_create(user=request.user)[0]

    def get(self, request):
        return Response(PreferenceSerializer(self.get_object(request)).data)

    def patch(self, request):
        serializer = PreferenceSerializer(self.get_object(request), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class ContactListView(APIView):
    def get(self, request):
        query = request.user.contacts.all().order_by("-is_favorite", "name")
        if request.query_params.get("search"):
            term = request.query_params["search"][:100]
            query = query.filter(Q(name__icontains=term) | Q(email__icontains=term) | Q(phone_number__icontains=term))
        contacts = list(query[:100])
        unmatched = {contact.email.lower() for contact in contacts if contact.email and not contact.linked_user_id}
        users_by_email = {user.email.lower(): user for user in User.objects.filter(email__in=unmatched, is_active=True)}
        for contact in contacts:
            user = users_by_email.get(contact.email.lower()) if contact.email and not contact.linked_user_id else None
            if user and user.id != request.user.id:
                contact.linked_user = user
                contact.save(update_fields=["linked_user"])
        return Response(ContactSerializer(contacts, many=True).data)

    def post(self, request):
        serializer = ContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data.get("email", "")
        if email and request.user.contacts.filter(email__iexact=email).exists():
            raise ValidationError({"email": "This contact is already saved."})
        linked_user = User.objects.filter(email__iexact=email).first() if email else None
        try:
            serializer.save(owner=request.user, linked_user=linked_user)
        except IntegrityError:
            raise ValidationError({"email": "This contact is already saved."})
        return Response(serializer.data, status=201)


class ContactDetailView(APIView):
    def get_object(self, request, pk):
        try:
            return request.user.contacts.get(pk=pk)
        except Contact.DoesNotExist:
            raise Http404

    def get(self, request, pk):
        return Response(ContactSerializer(self.get_object(request, pk)).data)

    def patch(self, request, pk):
        serializer = ContactSerializer(self.get_object(request, pk), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        if "email" in serializer.validated_data:
            email = serializer.validated_data["email"]
            if email and request.user.contacts.filter(email__iexact=email).exclude(pk=pk).exists():
                raise ValidationError({"email": "This contact is already saved."})
            linked_user = User.objects.filter(email__iexact=email).first() if email else None
            try:
                serializer.save(linked_user=linked_user)
            except IntegrityError:
                raise ValidationError({"email": "This contact is already saved."})
        else:
            serializer.save()
        return Response(serializer.data)

    def delete(self, request, pk):
        self.get_object(request, pk).delete()
        return Response(status=204)


def get_conversation(request, pk):
    try:
        return Conversation.objects.prefetch_related("participants__user").get(pk=pk, participants__user=request.user)
    except Conversation.DoesNotExist:
        raise Http404


class ConversationListView(APIView):
    def get(self, request):
        query = Conversation.objects.filter(participants__user=request.user).prefetch_related("participants__user").distinct()
        if request.query_params.get("channel") in ("internal", "whatsapp"):
            query = query.filter(channel_type=request.query_params["channel"])
        if request.query_params.get("archived") == "true":
            query = query.filter(participants__user=request.user, participants__is_archived=True)
        elif request.query_params.get("archived") != "all":
            query = query.filter(participants__user=request.user, participants__is_archived=False)
        if request.query_params.get("search"):
            term = request.query_params["search"][:100]
            query = query.filter(Q(title__icontains=term) | Q(participants__user__display_name__icontains=term)).distinct()
        return Response(ConversationSerializer(query.order_by("-last_activity_at")[:50], many=True, context={"request": request}).data)

    @transaction.atomic
    def post(self, request):
        ids = request.data.get("user_ids", [])
        if not isinstance(ids, list) or len(ids) < 1 or len(ids) > 100:
            raise ValidationError({"user_ids": "Choose 1 to 100 registered users."})
        try:
            ids = [uuid.UUID(str(value)) for value in ids]
        except (ValueError, TypeError):
            raise ValidationError({"user_ids": "Each user ID must be a UUID."})
        if len(ids) != len(set(ids)):
            raise ValidationError({"user_ids": "Choose each user once."})
        users = list(User.objects.filter(id__in=ids, is_active=True).exclude(id=request.user.id))
        if len(users) != len(set(ids)):
            raise ValidationError({"user_ids": "One or more users could not be found."})
        if Contact.objects.filter(owner=request.user, linked_user__in=users, is_blocked=True).exists():
            raise PermissionDenied("A selected contact is blocked.")
        is_group = len(users) > 1
        title = request.data.get("title", "").strip()[:120]
        if is_group and not title:
            raise ValidationError({"title": "A group name is required."})
        if not is_group:
            existing = Conversation.objects.filter(channel_type="internal", is_group=False, participants__user=request.user).filter(participants__user=users[0]).first()
            if existing:
                return Response(ConversationSerializer(existing, context={"request": request}).data)
        conversation = Conversation.objects.create(title=title, is_group=is_group, created_by=request.user)
        Participant.objects.create(conversation=conversation, user=request.user, role="admin")
        Participant.objects.bulk_create([Participant(conversation=conversation, user=user) for user in users])
        return Response(ConversationSerializer(conversation, context={"request": request}).data, status=201)


class ConversationDetailView(APIView):
    def get(self, request, pk):
        return Response(ConversationSerializer(get_conversation(request, pk), context={"request": request}).data)

    def patch(self, request, pk):
        conversation = get_conversation(request, pk)
        if not conversation.is_group or not conversation.participants.filter(user=request.user, role="admin").exists():
            raise PermissionDenied()
        conversation.title = str(request.data.get("title", conversation.title)).strip()[:120]
        conversation.save(update_fields=["title"])
        return Response(ConversationSerializer(get_conversation(request, pk), context={"request": request}).data)


class ConversationActionView(APIView):
    def post(self, request, pk, action):
        conversation = get_conversation(request, pk)
        participant = conversation.participants.get(user=request.user)
        if action == "archive":
            participant.is_archived = bool(request.data.get("value", True))
            participant.save(update_fields=["is_archived"])
        elif action == "mute":
            participant.is_muted = bool(request.data.get("value", True))
            participant.save(update_fields=["is_muted"])
        elif action == "pin":
            participant.is_pinned = bool(request.data.get("value", True))
            participant.save(update_fields=["is_pinned"])
        elif action == "read":
            participant.last_read_at = timezone.now()
            participant.save(update_fields=["last_read_at"])
            if Preference.objects.get_or_create(user=request.user)[0].read_receipts:
                receipts = MessageReceipt.objects.filter(message__conversation=conversation, recipient=request.user, read_at__isnull=True)
                affected = list(receipts.values_list("message_id", flat=True))
                receipts.update(read_at=participant.last_read_at, delivered_at=participant.last_read_at)
                for message in Message.objects.filter(id__in=affected):
                    if not message.receipts.filter(read_at__isnull=True).exists():
                        message.status = "read"
                        message.read_at = participant.last_read_at
                        message.save(update_fields=["status", "read_at"])
                        broadcast(conversation.id, {"event": "message.status_changed", "conversation_id": str(conversation.id), "message": MessageSerializer(message).data})
                broadcast(conversation.id, {"event": "conversation.read", "conversation_id": str(conversation.id), "user_id": str(request.user.id)})
        else:
            raise Http404
        return Response(ConversationSerializer(get_conversation(request, pk), context={"request": request}).data)


class MessageListView(APIView):
    def get(self, request, pk):
        conversation = get_conversation(request, pk)
        query = conversation.messages.select_related("sender").prefetch_related("attachments", "reactions").filter(deleted_at__isnull=True)
        before = request.query_params.get("before")
        if before:
            try:
                timestamp = timezone.datetime.fromisoformat(before.replace("Z", "+00:00"))
            except ValueError:
                raise ValidationError({"before": "Invalid timestamp."})
            before_id = request.query_params.get("before_id")
            if before_id:
                try:
                    message_id = uuid.UUID(before_id)
                except (ValueError, TypeError):
                    raise ValidationError({"before_id": "A UUID is required."})
                query = query.filter(Q(created_at__lt=timestamp) | Q(created_at=timestamp, id__lt=message_id))
            else:
                query = query.filter(created_at__lt=timestamp)
        elif request.query_params.get("before_id"):
            raise ValidationError({"before": "A timestamp is required with before_id."})
        items = list(query.order_by("-created_at", "-id")[:51])
        has_more = len(items) > 50
        items = items[:50]
        items.reverse()
        own_receipts = MessageReceipt.objects.filter(message__in=items, recipient=request.user, delivered_at__isnull=True)
        affected = list(own_receipts.values_list("message_id", flat=True))
        own_receipts.update(delivered_at=timezone.now())
        for message in Message.objects.filter(id__in=affected):
            if not message.receipts.filter(delivered_at__isnull=True).exists() and message.status == "sent":
                message.status = "delivered"
                message.delivered_at = timezone.now()
                message.save(update_fields=["status", "delivered_at"])
                broadcast(conversation.id, {"event": "message.status_changed", "conversation_id": str(conversation.id), "message": MessageSerializer(message).data})
        return Response({"results": MessageSerializer(items, many=True).data, "has_more": has_more})

    @transaction.atomic
    def post(self, request, pk):
        conversation = get_conversation(request, pk)
        if conversation.channel_type != "internal":
            raise ValidationError({"detail": "Use the WhatsApp send endpoint for this channel."})
        if not conversation.is_group:
            other_ids = conversation.participants.exclude(user=request.user).values_list("user_id", flat=True)
            if Contact.objects.filter(Q(owner=request.user, linked_user_id__in=other_ids) | Q(owner_id__in=other_ids, linked_user=request.user), is_blocked=True).exists():
                raise PermissionDenied("This contact is blocked.")
        body = str(request.data.get("body", "")).strip()
        if not body or len(body) > 4096:
            raise ValidationError({"body": "Enter 1 to 4096 characters."})
        try:
            client_id = uuid.UUID(str(request.data.get("client_message_id")))
        except (ValueError, TypeError):
            raise ValidationError({"client_message_id": "A UUID is required."})
        existing = Message.objects.filter(sender=request.user, client_message_id=client_id).first()
        if existing:
            if existing.conversation_id != conversation.id:
                raise ValidationError({"client_message_id": "Already used in another conversation."})
            return Response(MessageSerializer(existing).data)
        reply_to = None
        if request.data.get("reply_to"):
            try:
                reply_id = uuid.UUID(str(request.data["reply_to"]))
            except (ValueError, TypeError):
                raise ValidationError({"reply_to": "A UUID is required."})
            reply_to = conversation.messages.filter(pk=reply_id).first()
            if not reply_to:
                raise ValidationError({"reply_to": "Message not found."})
        now = timezone.now()
        try:
            with transaction.atomic():
                message = Message.objects.create(conversation=conversation, sender=request.user, body=body, client_message_id=client_id, reply_to=reply_to, status="sent", sent_at=now)
        except IntegrityError:
            message = Message.objects.get(sender=request.user, client_message_id=client_id)
            return Response(MessageSerializer(message).data)
        MessageReceipt.objects.bulk_create([MessageReceipt(message=message, recipient_id=uid) for uid in conversation.participants.exclude(user=request.user).values_list("user_id", flat=True)])
        conversation.last_activity_at = now
        conversation.save(update_fields=["last_activity_at"])
        serialized = MessageSerializer(message).data
        transaction.on_commit(lambda: broadcast(conversation.id, {"event": "message.created", "conversation_id": str(conversation.id), "message": serialized}))
        return Response(serialized, status=201)


class MessageDetailView(APIView):
    def get_object(self, request, pk):
        try:
            message = Message.objects.select_related("conversation", "sender").get(pk=pk)
        except Message.DoesNotExist:
            raise Http404
        get_conversation(request, message.conversation_id)
        return message

    def get(self, request, pk):
        return Response(MessageSerializer(self.get_object(request, pk)).data)

    def patch(self, request, pk):
        message = self.get_object(request, pk)
        if message.provider != "internal" or message.sender_id != request.user.id or message.deleted_at:
            raise PermissionDenied()
        body = str(request.data.get("body", "")).strip()
        if not body or len(body) > 4096:
            raise ValidationError({"body": "Enter 1 to 4096 characters."})
        message.body, message.edited_at = body, timezone.now()
        message.save(update_fields=["body", "edited_at"])
        serialized = MessageSerializer(message).data
        broadcast(message.conversation_id, {"event": "message.updated", "conversation_id": str(message.conversation_id), "message": serialized})
        return Response(serialized)

    def delete(self, request, pk):
        message = self.get_object(request, pk)
        if message.provider != "internal" or message.sender_id != request.user.id:
            raise PermissionDenied()
        message.body, message.deleted_at = "", timezone.now()
        message.save(update_fields=["body", "deleted_at"])
        broadcast(message.conversation_id, {"event": "message.deleted", "conversation_id": str(message.conversation_id), "message_id": str(message.id)})
        return Response(status=204)


class ReactionView(APIView):
    def post(self, request, pk):
        message = MessageDetailView().get_object(request, pk)
        if message.provider != "internal":
            raise ValidationError({"detail": "Reactions are only available in MyChat conversations."})
        emoji = str(request.data.get("emoji", ""))[:16]
        if not emoji:
            raise ValidationError({"emoji": "Choose a reaction."})
        reaction, created = Reaction.objects.get_or_create(message=message, user=request.user, emoji=emoji)
        if not created:
            reaction.delete()
        broadcast(message.conversation_id, {"event": "reaction.added" if created else "reaction.removed", "conversation_id": str(message.conversation_id), "message_id": str(message.id), "emoji": emoji, "user_id": str(request.user.id)})
        return Response({"active": created})


class AttachmentUploadView(APIView):
    def post(self, request, pk):
        conversation = get_conversation(request, pk)
        if conversation.channel_type != "internal":
            raise ValidationError({"detail": "This upload supports internal conversations only."})
        uploaded = request.FILES.get("file")
        if not uploaded or uploaded.size > 15 * 1024 * 1024:
            raise ValidationError({"file": "Choose a file smaller than 15 MB."})
        if uploaded.content_type not in SAFE_EXTENSIONS:
            raise ValidationError({"file": "File type is not supported."})
        if uploaded.content_type.startswith("image/"):
            try:
                Image.open(uploaded).verify()
                uploaded.seek(0)
            except (UnidentifiedImageError, ValueError, OSError):
                raise ValidationError({"file": "Image content is invalid."})
        kind = uploaded.content_type.split("/")[0]
        if kind not in ("image", "video", "audio"):
            kind = "document"
        display_name = uploaded.name[:255]
        uploaded.name = f"upload.{SAFE_EXTENSIONS[uploaded.content_type]}"
        now = timezone.now()
        message = Message.objects.create(conversation=conversation, sender=request.user, body=str(request.data.get("caption", ""))[:1024], message_type=kind, status="sent", sent_at=now)
        MessageReceipt.objects.bulk_create([MessageReceipt(message=message, recipient_id=uid) for uid in conversation.participants.exclude(user=request.user).values_list("user_id", flat=True)])
        Attachment.objects.create(message=message, file=uploaded, name=display_name, content_type=uploaded.content_type, size=uploaded.size)
        conversation.last_activity_at = now
        conversation.save(update_fields=["last_activity_at"])
        serialized = MessageSerializer(message).data
        broadcast(conversation.id, {"event": "message.created", "conversation_id": str(conversation.id), "message": serialized})
        return Response(serialized, status=201)


class AttachmentDownloadView(APIView):
    def get(self, request, pk):
        try:
            attachment = Attachment.objects.select_related("message").get(pk=pk)
        except Attachment.DoesNotExist:
            raise Http404
        get_conversation(request, attachment.message.conversation_id)
        inline = attachment.content_type.startswith(("image/", "video/", "audio/"))
        return FileResponse(attachment.file.open("rb"), as_attachment=not inline, filename=attachment.name, content_type=attachment.content_type)


class StoryListView(APIView):
    def get(self, request):
        related_ids = Contact.objects.filter(owner=request.user, linked_user__isnull=False, is_blocked=False).values_list("linked_user_id", flat=True)
        blocked_by = Contact.objects.filter(linked_user=request.user, is_blocked=True).values_list("owner_id", flat=True)
        stories = Story.objects.filter(expires_at__gt=timezone.now()).filter(Q(author=request.user) | Q(author_id__in=related_ids, visibility="contacts")).exclude(author_id__in=blocked_by).select_related("author").order_by("-created_at")[:100]
        return Response(StorySerializer(stories, many=True).data)

    def post(self, request):
        serializer = StorySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not serializer.validated_data.get("body") and not request.FILES.get("media"):
            raise ValidationError({"body": "Add text or media."})
        media = request.FILES.get("media")
        if media and (media.size > 15 * 1024 * 1024 or media.content_type not in {"image/jpeg", "image/png", "image/gif", "image/webp", "video/mp4", "video/webm"}):
            raise ValidationError({"media": "Choose an image or video smaller than 15 MB."})
        if media and media.content_type.startswith("image/"):
            try:
                Image.open(media).verify()
                media.seek(0)
            except (UnidentifiedImageError, ValueError, OSError):
                raise ValidationError({"media": "Image content is invalid."})
        if media:
            media.name = f"story.{SAFE_EXTENSIONS[media.content_type]}"
        story = serializer.save(author=request.user, expires_at=timezone.now() + timedelta(hours=24))
        return Response(StorySerializer(story).data, status=201)


class StoryDetailView(APIView):
    def get_object(self, request, pk):
        try:
            story = Story.objects.get(pk=pk, expires_at__gt=timezone.now())
        except Story.DoesNotExist:
            raise Http404
        if story.author_id != request.user.id and (story.visibility != "contacts" or not Contact.objects.filter(owner=request.user, linked_user=story.author, is_blocked=False).exists() or Contact.objects.filter(owner=story.author, linked_user=request.user, is_blocked=True).exists()):
            raise Http404
        return story

    def get(self, request, pk):
        return Response(StorySerializer(self.get_object(request, pk)).data)

    def delete(self, request, pk):
        story = self.get_object(request, pk)
        if story.author_id != request.user.id:
            raise PermissionDenied()
        story.delete()
        return Response(status=204)


class StoryViewView(APIView):
    def post(self, request, pk):
        story = StoryDetailView().get_object(request, pk)
        if story.author_id != request.user.id:
            StoryView.objects.get_or_create(story=story, viewer=request.user)
        return Response({"viewed": True})


class StoryMediaView(APIView):
    def get(self, request, pk):
        story = StoryDetailView().get_object(request, pk)
        if not story.media:
            raise Http404
        return FileResponse(story.media.open("rb"), as_attachment=False, content_type=mimetypes.guess_type(story.media.name)[0] or "application/octet-stream")


class GroupListView(APIView):
    def get(self, request):
        groups = Conversation.objects.filter(channel_type="internal", is_group=True, participants__user=request.user).prefetch_related("participants__user").order_by("-last_activity_at")[:50]
        return Response(ConversationSerializer(groups, many=True, context={"request": request}).data)

    def post(self, request):
        if not isinstance(request.data.get("user_ids"), list) or len(request.data["user_ids"]) < 2:
            raise ValidationError({"user_ids": "Choose at least two group members."})
        return ConversationListView().post(request)


class GroupDetailView(APIView):
    def get(self, request, pk):
        group = get_conversation(request, pk)
        if not group.is_group:
            raise Http404
        return Response(ConversationSerializer(get_conversation(request, pk), context={"request": request}).data)

    def patch(self, request, pk):
        return ConversationDetailView().patch(request, pk)


class GroupMembersView(APIView):
    def post(self, request, pk):
        group = get_conversation(request, pk)
        if not group.is_group or not group.participants.filter(user=request.user, role="admin").exists():
            raise PermissionDenied()
        try:
            user_id = uuid.UUID(str(request.data.get("user_id")))
        except (ValueError, TypeError):
            raise ValidationError({"user_id": "A UUID is required."})
        try:
            user = User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            raise ValidationError({"user_id": "User not found."})
        Participant.objects.get_or_create(conversation=group, user=user)
        return Response(ConversationSerializer(get_conversation(request, pk), context={"request": request}).data)


class GroupMemberDetailView(APIView):
    def delete(self, request, pk, member_id):
        group = get_conversation(request, pk)
        if not group.is_group:
            raise Http404
        if request.user.id != member_id and not group.participants.filter(user=request.user, role="admin").exists():
            raise PermissionDenied()
        with transaction.atomic():
            member = group.participants.select_for_update().filter(user_id=member_id).first()
            if not member:
                raise Http404
            if member.role == "admin" and not group.participants.exclude(pk=member.pk).filter(role="admin").exists():
                successor = group.participants.exclude(pk=member.pk).order_by("created_at").first()
                if successor:
                    successor.role = "admin"
                    successor.save(update_fields=["role"])
            member.delete()
            if not Participant.objects.filter(conversation=group).exists():
                group.delete()
        return Response(status=204)
