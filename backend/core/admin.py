from django.contrib import admin
from .models import Attachment, Contact, Conversation, Message, OutboundJob, Participant, PendingProviderStatus, Preference, Story, User, WebhookEvent, WhatsAppBusinessAccount, WhatsAppContact, WhatsAppTemplate


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "display_name", "is_staff", "is_active")
    search_fields = ("email", "display_name")
    fields = ("email", "display_name", "is_staff", "is_active", "email_verified")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "channel_type", "title", "created_by", "last_activity_at")
    exclude = ("remote_phone",)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ("id", "conversation", "provider", "status", "created_at")
    exclude = ("body", "external_sender_id", "provider_message_id")


for model in (Contact, Participant, Preference, Attachment, Story, OutboundJob, WebhookEvent, PendingProviderStatus, WhatsAppBusinessAccount, WhatsAppContact, WhatsAppTemplate):
    admin.site.register(model)
