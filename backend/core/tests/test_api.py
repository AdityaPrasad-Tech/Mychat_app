import asyncio
import hashlib
import hmac
import json
import tempfile
import uuid
from datetime import timedelta
from unittest.mock import patch
import pytest
from django.test import override_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from channels.testing import WebsocketCommunicator
from rest_framework.test import APIClient
import core.tasks
from core.consumers import ChatConsumer
from core.models import Contact, Conversation, Message, Participant, PendingProviderStatus, Story, User, WhatsAppBusinessAccount, WhatsAppContact, WebhookEvent
from core.realtime import broadcast
from core.serializers import MessageSerializer
from core.ws_auth import user_from_token


@pytest.fixture(autouse=True)
def local_http():
    with override_settings(SECURE_SSL_REDIRECT=False):
        yield


@pytest.fixture
def users(db):
    alice = User.objects.create_user("alice@example.test", "DemoPass123!", display_name="Alice")
    bob = User.objects.create_user("bob@example.test", "DemoPass123!", display_name="Bob")
    charlie = User.objects.create_user("charlie@example.test", "DemoPass123!", display_name="Charlie")
    return alice, bob, charlie


@pytest.fixture
def chat(users):
    alice, bob, _ = users
    c = Conversation.objects.create(created_by=alice)
    Participant.objects.create(conversation=c, user=alice)
    Participant.objects.create(conversation=c, user=bob)
    return c


@pytest.mark.django_db
def test_registration_login_and_contact_isolation(users):
    alice, bob, _ = users
    client = APIClient()
    response = client.post("/api/v1/auth/register/", {"email": "new@example.test", "display_name": "New", "password": "AnotherPass123!"})
    assert response.status_code == 201
    assert client.get("/api/v1/auth/me/").status_code == 200
    client.post("/api/v1/auth/logout/")
    assert client.get("/api/v1/auth/me/").status_code == 403
    assert client.post("/api/v1/auth/login/", {"email": "new@example.test", "password": "AnotherPass123!"}).status_code == 200
    client.force_authenticate(alice)
    created = client.post("/api/v1/contacts/", {"name": "Bob", "email": bob.email})
    assert created.status_code == 201
    assert client.post("/api/v1/contacts/", {"name": "Bob again", "email": bob.email}).status_code == 400
    contact_id = created.data["id"]
    client.force_authenticate(bob)
    assert client.get(f"/api/v1/contacts/{contact_id}/").status_code == 404


@pytest.mark.django_db
def test_registration_requires_csrf():
    client = APIClient(enforce_csrf_checks=True)
    data = {"email": "csrf@example.test", "display_name": "CSRF", "password": "AnotherPass123!"}
    assert client.post("/api/v1/auth/register/", data).status_code == 403
    token = client.get("/api/v1/auth/csrf/").data["csrfToken"]
    assert client.post("/api/v1/auth/register/", data, HTTP_X_CSRFTOKEN=token).status_code == 201


@pytest.mark.django_db
def test_friend_can_join_after_contact_is_saved_and_receive_message(users):
    alice, _, _ = users
    client = APIClient()
    client.force_authenticate(alice)
    saved = client.post("/api/v1/contacts/", {"name": "New friend", "email": "friend@example.test"})
    assert saved.status_code == 201
    assert saved.data["linked_user"] is None

    client.force_authenticate(user=None)
    registered = client.post("/api/v1/auth/register/", {"email": "friend@example.test", "display_name": "Friend", "password": "AnotherPass123!"})
    assert registered.status_code == 201
    friend_id = registered.data["id"]
    assert str(Contact.objects.get(pk=saved.data["id"]).linked_user_id) == friend_id

    client.force_authenticate(alice)
    chat_response = client.post("/api/v1/conversations/", {"user_ids": [friend_id]}, format="json")
    assert chat_response.status_code == 201
    conversation_id = chat_response.data["id"]
    with patch("core.views.broadcast"):
        sent = client.post(f"/api/v1/conversations/{conversation_id}/messages/", {"body": "Hi friend", "client_message_id": str(uuid.uuid4())})
    assert sent.status_code == 201

    client.force_authenticate(User.objects.get(pk=friend_id))
    assert any(item["id"] == conversation_id for item in client.get("/api/v1/conversations/").data)
    assert client.get(f"/api/v1/conversations/{conversation_id}/messages/").data["results"][0]["body"] == "Hi friend"


@pytest.mark.django_db
def test_older_messages_button_has_a_real_next_page(users, chat):
    alice, _, _ = users
    Message.objects.bulk_create([Message(conversation=chat, sender=alice, body=f"Message {index}") for index in range(51)])
    client = APIClient()
    client.force_authenticate(alice)
    url = f"/api/v1/conversations/{chat.id}/messages/"
    latest = client.get(url)
    assert latest.status_code == 200
    assert len(latest.data["results"]) == 50
    assert latest.data["has_more"] is True
    older = client.get(url, {"before": latest.data["results"][0]["created_at"], "before_id": latest.data["results"][0]["id"]})
    assert older.status_code == 200
    assert len(older.data["results"]) == 1
    assert older.data["has_more"] is False


@pytest.mark.django_db
def test_internal_message_persists_and_deduplicates(users, chat):
    alice, bob, charlie = users
    client = APIClient()
    client.force_authenticate(alice)
    key = str(uuid.uuid4())
    url = f"/api/v1/conversations/{chat.id}/messages/"
    with patch("core.views.broadcast"):
        first = client.post(url, {"body": "Hello Bob", "client_message_id": key})
        second = client.post(url, {"body": "Hello Bob", "client_message_id": key})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["id"] == second.data["id"]
    assert Message.objects.filter(conversation=chat).count() == 1
    client.force_authenticate(charlie)
    assert client.get(url).status_code == 404
    client.force_authenticate(bob)
    with patch("core.views.broadcast"):
        assert client.get(url).status_code == 200
        marked = client.post(f"/api/v1/conversations/{chat.id}/read/", {})
        assert marked.status_code == 200
        assert marked.data["unread_count"] == 0
    assert Message.objects.get(pk=first.data["id"]).status == "read"


@pytest.mark.django_db
def test_realtime_event_contains_only_json_values(users, chat):
    alice, _, _ = users
    message = Message.objects.create(conversation=chat, sender=alice, body="Ready")
    events = []

    class Layer:
        async def group_send(self, group, event):
            json.dumps(event)
            events.append((group, event))

    with patch("core.realtime.get_channel_layer", return_value=Layer()):
        broadcast(chat.id, {"event": "message.created", "conversation_id": str(chat.id), "message": MessageSerializer(message).data})
    assert events[0][1]["payload"]["message"]["id"] == str(message.id)


@pytest.mark.django_db(transaction=True)
def test_websocket_token_requires_live_login_session(users):
    alice, _, _ = users
    client = APIClient()
    assert client.post("/api/v1/auth/login/", {"email": alice.email, "password": "DemoPass123!"}).status_code == 200
    response = client.get("/api/v1/auth/websocket-token/")
    assert response.status_code == 200
    token = response.data["token"]
    assert asyncio.run(user_from_token(token)).id == alice.id
    assert asyncio.run(user_from_token(token + "bad")) is None
    client.post("/api/v1/auth/logout/")
    assert asyncio.run(user_from_token(token)) is None


@pytest.mark.django_db
def test_group_permission_and_story_expiration(users):
    alice, bob, charlie = users
    client = APIClient()
    client.force_authenticate(alice)
    assert client.post("/api/v1/groups/", {"title": "Bad", "user_ids": ["invalid", str(bob.id)]}, format="json").status_code == 400
    response = client.post("/api/v1/groups/", {"title": "Team", "user_ids": [str(bob.id), str(charlie.id)]}, format="json")
    assert response.status_code == 201
    group_id = response.data["id"]
    client.force_authenticate(bob)
    assert client.patch(f"/api/v1/groups/{group_id}/", {"title": "Hijacked"}).status_code == 403
    expired = Story.objects.create(author=alice, body="Old", expires_at=timezone.now() - timedelta(seconds=1))
    Contact.objects.create(owner=bob, name="Alice", email=alice.email, linked_user=alice)
    assert all(item["id"] != str(expired.id) for item in client.get("/api/v1/stories/").data)


@pytest.mark.django_db
def test_group_management_keeps_an_admin_and_enforces_membership(users):
    alice, bob, charlie = users
    dana = User.objects.create_user("dana@example.test", "DemoPass123!", display_name="Dana")
    client = APIClient()
    client.force_authenticate(alice)
    created = client.post("/api/v1/groups/", {"title": "Friends", "user_ids": [str(bob.id), str(charlie.id)]}, format="json")
    assert created.status_code == 201
    group_id = created.data["id"]

    client.force_authenticate(bob)
    assert client.delete(f"/api/v1/groups/{group_id}/members/{charlie.id}/").status_code == 403

    client.force_authenticate(alice)
    assert client.patch(f"/api/v1/groups/{group_id}/", {"title": "Weekend friends"}).data["title"] == "Weekend friends"
    assert client.post(f"/api/v1/groups/{group_id}/members/", {"user_id": str(dana.id)}).status_code == 200
    assert client.delete(f"/api/v1/groups/{group_id}/members/{charlie.id}/").status_code == 204
    assert client.delete(f"/api/v1/groups/{group_id}/members/{alice.id}/").status_code == 204

    group = Conversation.objects.get(pk=group_id)
    assert group.participants.filter(role="admin").count() == 1
    client.force_authenticate(charlie)
    assert client.get(f"/api/v1/groups/{group_id}/").status_code == 404
    client.force_authenticate(bob)
    assert client.patch(f"/api/v1/groups/{group_id}/", {"title": "Still managed"}).status_code == 200
    assert client.delete(f"/api/v1/groups/{group_id}/members/{dana.id}/").status_code == 204
    assert client.delete(f"/api/v1/groups/{group_id}/members/{bob.id}/").status_code == 204
    assert not Conversation.objects.filter(pk=group_id).exists()


@pytest.mark.django_db
@override_settings(WHATSAPP_APP_SECRET="test-secret", WHATSAPP_VERIFY_TOKEN="verify-token")
def test_webhook_requires_signature_and_deduplicates(users):
    alice, _, _ = users
    WhatsAppBusinessAccount.objects.create(owner=alice, waba_id="waba", phone_number_id="phone-id")
    payload = {"object": "whatsapp_business_account", "entry": [{"changes": [{"value": {"metadata": {"phone_number_id": "phone-id"}, "contacts": [{"wa_id": "14155552671", "profile": {"name": "Customer"}}], "messages": [{"id": "wamid.one", "from": "14155552671", "type": "text", "text": {"body": "Hello"}}]}}]}]}
    raw = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    client = APIClient()
    assert client.post("/api/v1/webhooks/whatsapp/", raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256="sha256=bad").status_code == 403
    with patch.object(core.tasks.process_whatsapp_event, "delay") as enqueue:
        assert client.post("/api/v1/webhooks/whatsapp/", raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=sig).status_code == 200
        assert client.post("/api/v1/webhooks/whatsapp/", raw, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=sig).status_code == 200
    assert WebhookEvent.objects.count() == 1
    enqueue.assert_called_once()


@pytest.mark.django_db
def test_whatsapp_window_policy(users):
    from core.whatsapp import validate_outbound
    from rest_framework.exceptions import ValidationError
    alice, _, _ = users
    account = WhatsAppBusinessAccount.objects.create(owner=alice, waba_id="waba", phone_number_id="phone-id")
    with override_settings(WHATSAPP_ACCESS_TOKEN="token", WHATSAPP_PHONE_NUMBER_ID="phone-id", WHATSAPP_APP_SECRET="secret", WHATSAPP_VERIFY_TOKEN="verify"):
        with pytest.raises(ValidationError) as exc:
            validate_outbound(account, "+14155552671", "text")
        assert exc.value.detail["code"] == "WHATSAPP_TEMPLATE_REQUIRED"
        WhatsAppContact.objects.create(account=account, phone_number="+14155552671", last_inbound_at=timezone.now())
        validate_outbound(account, "+14155552671", "text")


@pytest.mark.django_db
def test_out_of_order_provider_status(users):
    from core.whatsapp import apply_pending_status, ingest_status
    alice, _, _ = users
    with patch("core.whatsapp.broadcast"):
        ingest_status({"id": "wamid.pending", "status": "read"})
        assert PendingProviderStatus.objects.count() == 1
        conversation = Conversation.objects.create(channel_type="whatsapp", remote_phone="+14155552671", created_by=alice)
        message = Message.objects.create(conversation=conversation, sender=alice, provider="whatsapp", body="Hello", provider_message_id="wamid.pending", status="sent")
        apply_pending_status("wamid.pending")
    message.refresh_from_db()
    assert message.status == "read"
    assert PendingProviderStatus.objects.count() == 0


@pytest.mark.django_db
def test_attachment_requires_conversation_membership(users, chat):
    alice, bob, charlie = users
    client = APIClient()
    with tempfile.TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
        client.force_authenticate(alice)
        with patch("core.views.broadcast"):
            response = client.post(f"/api/v1/conversations/{chat.id}/attachments/", {"file": SimpleUploadedFile("note.txt", b"private", content_type="text/plain")})
        assert response.status_code == 201
        attachment_id = response.data["attachments"][0]["id"]
        client.force_authenticate(charlie)
        assert client.get(f"/api/v1/attachments/{attachment_id}/download/").status_code == 404
        client.force_authenticate(bob)
        download = client.get(f"/api/v1/attachments/{attachment_id}/download/")
        assert download.status_code == 200
        assert b"".join(download.streaming_content) == b"private"


@pytest.mark.django_db(transaction=True)
def test_websocket_subscription_checks_membership(users, chat):
    alice, _, charlie = users

    async def scenario(user, accepted):
        connection = WebsocketCommunicator(ChatConsumer.as_asgi(), "/ws/chat/")
        connection.scope["user"] = user
        connected, _ = await connection.connect()
        assert connected
        assert (await connection.receive_json_from())["event"] == "connected"
        await connection.send_json_to({"event": "subscribe", "conversation_id": str(chat.id)})
        response = await connection.receive_json_from()
        assert response["event"] == ("subscribed" if accepted else "error")
        await connection.disconnect()

    with override_settings(CHANNEL_LAYERS={"default": {"BACKEND": "channels.layers.InMemoryChannelLayer"}}):
        asyncio.run(scenario(alice, True))
        asyncio.run(scenario(charlie, False))
