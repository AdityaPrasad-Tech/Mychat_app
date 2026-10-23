import json
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.serializers.json import DjangoJSONEncoder


def broadcast(conversation_id, payload):
    layer = get_channel_layer()
    safe_payload = json.loads(json.dumps(payload, cls=DjangoJSONEncoder))
    async_to_sync(layer.group_send)(f"chat_{conversation_id}", {"type": "chat.event", "payload": safe_payload})
