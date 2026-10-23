from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.sessions.models import Session
from django.core import signing
from django.utils import timezone


@database_sync_to_async
def user_from_token(token):
    try:
        payload = signing.loads(token, salt="mychat-websocket", max_age=90)
        user_id = payload["user_id"]
        session_key = payload["session_key"]
        session = Session.objects.filter(session_key=session_key, expire_date__gt=timezone.now()).first()
        if not session or str(session.get_decoded().get("_auth_user_id")) != user_id:
            return None
        return get_user_model().objects.filter(pk=user_id, is_active=True).first()
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return None


class WebSocketTokenMiddleware:
    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        tokens = parse_qs(scope.get("query_string", b"").decode("ascii", errors="ignore")).get("token", [])
        if len(tokens) == 1:
            user = await user_from_token(tokens[0])
            if user:
                scope = {**scope, "user": user}
        return await self.inner(scope, receive, send)
