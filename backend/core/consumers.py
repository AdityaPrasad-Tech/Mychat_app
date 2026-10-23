import json
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from .models import Participant


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        if not self.scope["user"].is_authenticated:
            await self.close(code=4401)
            return
        self.groups_joined = set()
        await self.accept()
        await self.send_json({"event": "connected"})

    @database_sync_to_async
    def can_access(self, conversation_id):
        return Participant.objects.filter(conversation_id=conversation_id, user=self.scope["user"]).exists()

    async def receive(self, text_data=None, bytes_data=None):
        if not text_data or len(text_data) > 4096:
            await self.close(code=4400)
            return
        try:
            data = json.loads(text_data)
        except ValueError:
            return
        event = data.get("event")
        conversation_id = data.get("conversation_id")
        if event == "ping":
            await self.send_json({"event": "pong"})
            return
        if not isinstance(conversation_id, str) or not await self.can_access(conversation_id):
            await self.send_json({"event": "error", "message": "Conversation access denied."})
            return
        group = f"chat_{conversation_id}"
        if event == "subscribe":
            await self.channel_layer.group_add(group, self.channel_name)
            self.groups_joined.add(group)
            await self.send_json({"event": "subscribed", "conversation_id": conversation_id})
        elif event == "unsubscribe":
            await self.channel_layer.group_discard(group, self.channel_name)
            self.groups_joined.discard(group)
        elif event in ("typing.started", "typing.stopped") and group in self.groups_joined:
            await self.channel_layer.group_send(group, {"type": "chat.event", "payload": {
                "event": event, "conversation_id": conversation_id, "user_id": str(self.scope["user"].id)
            }})

    async def chat_event(self, event):
        payload = event["payload"]
        conversation_id = payload.get("conversation_id")
        if conversation_id and not await self.can_access(conversation_id):
            group = f"chat_{conversation_id}"
            await self.channel_layer.group_discard(group, self.channel_name)
            self.groups_joined.discard(group)
            return
        await self.send_json(payload)

    async def disconnect(self, close_code):
        for group in getattr(self, "groups_joined", set()):
            await self.channel_layer.group_discard(group, self.channel_name)
