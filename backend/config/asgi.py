import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

django_asgi_app = get_asgi_application()
from core.routing import websocket_urlpatterns  # noqa: E402 - models need the app registry initialized
from core.ws_auth import WebSocketTokenMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(WebSocketTokenMiddleware(URLRouter(websocket_urlpatterns)))),
})
