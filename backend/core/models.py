import uuid
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


def private_upload_path(instance, filename):
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    suffix = suffix if suffix.isalnum() and len(suffix) <= 8 else "bin"
    return f"private/{uuid.uuid4().hex}.{suffix}"


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra):
        if not email:
            raise ValueError("Email is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password, **extra):
        extra.update(is_staff=True, is_superuser=True, is_active=True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin, UUIDModel):
    email = models.EmailField(unique=True)
    display_name = models.CharField(max_length=100)
    bio = models.CharField(max_length=255, blank=True)
    avatar = models.ImageField(upload_to="avatars/", blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    last_seen = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["display_name"]
    objects = UserManager()

    def __str__(self):
        return self.display_name or self.email


class Preference(UUIDModel):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preferences")
    theme = models.CharField(max_length=10, default="system")
    notifications = models.BooleanField(default=True)
    read_receipts = models.BooleanField(default=True)
    enter_to_send = models.BooleanField(default=True)


class Contact(UUIDModel):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=100)
    phone_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True)
    is_favorite = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)
    linked_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="saved_by")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["owner", "email"], condition=~models.Q(email=""), name="unique_owner_contact_email")]


class Conversation(UUIDModel):
    INTERNAL = "internal"
    WHATSAPP = "whatsapp"
    CHANNELS = [(INTERNAL, "Internal"), (WHATSAPP, "WhatsApp")]
    channel_type = models.CharField(max_length=12, choices=CHANNELS, default=INTERNAL)
    title = models.CharField(max_length=120, blank=True)
    is_group = models.BooleanField(default=False)
    created_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL)
    remote_phone = models.CharField(max_length=32, blank=True)
    last_activity_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-last_activity_at"]


class Participant(UUIDModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=12, default="member")
    last_read_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    is_muted = models.BooleanField(default=False)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="unique_participant")]
        indexes = [models.Index(fields=["user", "is_archived"])]


class Message(UUIDModel):
    STATUS = [(v, v.title()) for v in ("pending", "queued", "sent", "delivered", "read", "failed")]
    TYPES = [(v, v.title()) for v in ("text", "image", "video", "audio", "document", "template")]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    external_sender_id = models.CharField(max_length=64, blank=True)
    provider = models.CharField(max_length=12, default=Conversation.INTERNAL)
    message_type = models.CharField(max_length=12, choices=TYPES, default="text")
    body = models.TextField(blank=True)
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL)
    provider_message_id = models.CharField(max_length=255, null=True, blank=True, unique=True)
    client_message_id = models.UUIDField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default="pending")
    error_code = models.CharField(max_length=80, blank=True)
    error_message = models.CharField(max_length=255, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [models.UniqueConstraint(fields=["sender", "client_message_id"], condition=models.Q(client_message_id__isnull=False), name="unique_sender_client_message")]
        indexes = [models.Index(fields=["conversation", "created_at"]), models.Index(fields=["status", "created_at"])]


class Reaction(UUIDModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    emoji = models.CharField(max_length=16)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "user", "emoji"], name="unique_reaction")]


class Attachment(UUIDModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to=private_upload_path)
    name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100)
    size = models.PositiveIntegerField()


class Story(UUIDModel):
    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="stories")
    body = models.TextField(blank=True)
    background = models.CharField(max_length=20, default="#128C7E")
    media = models.FileField(upload_to=private_upload_path, blank=True)
    expires_at = models.DateTimeField()
    visibility = models.CharField(max_length=12, choices=[("contacts", "Contacts"), ("private", "Private")], default="contacts")


class StoryView(UUIDModel):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name="views")
    viewer = models.ForeignKey(User, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["story", "viewer"], name="unique_story_view")]


class MessageReceipt(UUIDModel):
    message = models.ForeignKey(Message, on_delete=models.CASCADE, related_name="receipts")
    recipient = models.ForeignKey(User, on_delete=models.CASCADE)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["message", "recipient"], name="unique_message_receipt")]


class WhatsAppTemplate(UUIDModel):
    account = models.ForeignKey("WhatsAppBusinessAccount", null=True, blank=True, on_delete=models.CASCADE, related_name="templates")
    name = models.CharField(max_length=255)
    language = models.CharField(max_length=20)
    status = models.CharField(max_length=30, default="pending")
    category = models.CharField(max_length=30, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "name", "language"], name="unique_account_template_locale")]


class WhatsAppBusinessAccount(UUIDModel):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="whatsapp_accounts")
    waba_id = models.CharField(max_length=64)
    phone_number_id = models.CharField(max_length=64, unique=True)
    display_phone_number = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)
    last_webhook_at = models.DateTimeField(null=True, blank=True)


class WhatsAppContact(UUIDModel):
    account = models.ForeignKey(WhatsAppBusinessAccount, null=True, blank=True, on_delete=models.CASCADE, related_name="contacts")
    phone_number = models.CharField(max_length=32)
    name = models.CharField(max_length=100, blank=True)
    opted_in_at = models.DateTimeField(null=True, blank=True)
    last_inbound_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["account", "phone_number"], name="unique_account_whatsapp_contact")]


class WebhookEvent(UUIDModel):
    identity = models.CharField(max_length=255, unique=True)
    payload = models.JSONField()
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=255, blank=True)


class PendingProviderStatus(UUIDModel):
    provider_message_id = models.CharField(max_length=255)
    status = models.CharField(max_length=20)
    payload = models.JSONField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["provider_message_id", "status"], name="unique_pending_provider_status")]


class OutboundJob(UUIDModel):
    message = models.OneToOneField(Message, on_delete=models.CASCADE)
    state = models.CharField(max_length=16, default="queued")
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=255, blank=True)
    payload = models.JSONField(default=dict)
