from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import AccessToken


User = get_user_model()


@database_sync_to_async
def get_user_from_token(token):
    try:
        access_token = AccessToken(token)
        user_id = access_token.get("user_id")
        return User.objects.get(id=user_id, is_active=True)
    except Exception:
        return AnonymousUser()


class JWTAuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        token = None

        query_string = scope.get("query_string", b"").decode()
        query_params = parse_qs(query_string)

        if "token" in query_params:
            token = query_params["token"][0]

        if not token:
            headers = dict(scope.get("headers", []))
            auth_header = headers.get(b"authorization")

            if auth_header:
                auth_text = auth_header.decode()

                if auth_text.lower().startswith("bearer "):
                    token = auth_text.split(" ", 1)[1].strip()

        scope["user"] = await get_user_from_token(token) if token else AnonymousUser()

        return await self.app(scope, receive, send)