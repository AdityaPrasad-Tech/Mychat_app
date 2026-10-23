import re
import mimetypes
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import Attachment, Contact, Conversation, Message, Participant, Preference, Reaction, Story, User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "display_name", "bio", "email_verified", "avatar"]
        read_only_fields = ["id", "email", "email_verified"]


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    display_name = serializers.CharField(max_length=100)
    password = serializers.CharField(write_only=True)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email exists.")
        return value.lower()

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        Preference.objects.create(user=user)
        return user


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preference
        fields = ["theme", "notifications", "read_receipts", "enter_to_send"]


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = ["id", "name", "phone_number", "email", "notes", "is_favorite", "is_blocked", "linked_user", "created_at"]
        read_only_fields = ["id", "linked_user", "created_at"]

    def validate_phone_number(self, value):
        if value and not re.fullmatch(r"\+[1-9]\d{1,14}", value):
            raise serializers.ValidationError("Use E.164 format, for example +14155552671.")
        return value


class ParticipantSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)

    class Meta:
        model = Participant
        fields = ["id", "user", "role", "last_read_at", "is_archived", "is_pinned", "is_muted"]


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = ["id", "name", "content_type", "size"]


class ReactionSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source="user.id", read_only=True)

    class Meta:
        model = Reaction
        fields = ["id", "emoji", "user_id"]


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    reactions = ReactionSerializer(many=True, read_only=True)

    class Meta:
        model = Message
        fields = ["id", "conversation", "sender", "external_sender_id", "provider", "message_type", "body", "reply_to", "status", "client_message_id", "created_at", "sent_at", "delivered_at", "read_at", "edited_at", "deleted_at", "attachments", "reactions"]


class ConversationSerializer(serializers.ModelSerializer):
    participants = ParticipantSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = ["id", "channel_type", "title", "is_group", "remote_phone", "last_activity_at", "participants", "last_message", "unread_count"]

    def get_last_message(self, obj):
        message = obj.messages.order_by("-created_at").first()
        return MessageSerializer(message).data if message else None

    def get_unread_count(self, obj):
        user = self.context["request"].user
        part = next((p for p in obj.participants.all() if p.user_id == user.id), None)
        if not part:
            return 0
        query = obj.messages.exclude(sender=user).filter(deleted_at__isnull=True)
        if part.last_read_at:
            query = query.filter(created_at__gt=part.last_read_at)
        return query.count()


class StorySerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)
    view_count = serializers.IntegerField(source="views.count", read_only=True)
    media = serializers.FileField(write_only=True, required=False)
    media_url = serializers.SerializerMethodField()
    media_type = serializers.SerializerMethodField()

    def get_media_url(self, obj):
        return f"/api/v1/stories/{obj.id}/media/" if obj.media else None

    def get_media_type(self, obj):
        return mimetypes.guess_type(obj.media.name)[0] if obj.media else None

    class Meta:
        model = Story
        fields = ["id", "author", "body", "background", "media", "media_url", "media_type", "visibility", "created_at", "expires_at", "view_count"]
        read_only_fields = ["id", "author", "media_url", "media_type", "created_at", "expires_at", "view_count"]
