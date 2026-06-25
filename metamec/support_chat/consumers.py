from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.utils import timezone

from .models import ChatConversation, ChatMessage


def is_admin_user(user):
    if not user or not user.is_authenticated:
        return False

    if getattr(user, "is_staff", False) or getattr(user, "is_superuser", False):
        return True

    return str(getattr(user, "role", "")).lower() in [
        "admin",
        "super_admin",
        "administrator",
    ]


def user_payload(user):
    return {
        "id": str(user.id),
        "name": getattr(user, "full_name", None) or getattr(user, "email_address", None),
        "email": getattr(user, "email_address", None) or getattr(user, "email", None),
        "role": getattr(user, "role", None),
        "isAdmin": is_admin_user(user),
    }


class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        self.user = self.scope.get("user")
        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.group_name = f"chat_{self.conversation_id}"

        if not self.user or not self.user.is_authenticated:
            await self.close(code=4401)
            return

        allowed = await self.can_access_conversation()

        if not allowed:
            await self.close(code=4403)
            return

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        await self.send_json(
            {
                "type": "connection_established",
                "conversationId": self.conversation_id,
                "user": user_payload(self.user),
            }
        )

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "chat.presence",
                "event": "online",
                "user": user_payload(self.user),
            },
        )

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.presence",
                    "event": "offline",
                    "user": user_payload(self.user) if self.user and self.user.is_authenticated else None,
                },
            )
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = content.get("action")

        if action == "send_message":
            message_text = str(content.get("message") or "").strip()
            client_message_id = content.get("clientMessageId")

            if not message_text:
                await self.send_json(
                    {
                        "type": "error",
                        "message": "Message cannot be empty.",
                    }
                )
                return

            message_data = await self.create_message(message_text)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.message",
                    "message": message_data,
                    "clientMessageId": client_message_id,
                },
            )

        elif action == "typing":
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.typing",
                    "user": user_payload(self.user),
                    "isTyping": bool(content.get("isTyping", True)),
                },
            )

        elif action == "mark_read":
            read_data = await self.mark_messages_read()

            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.read",
                    "reader": user_payload(self.user),
                    "data": read_data,
                },
            )

        else:
            await self.send_json(
                {
                    "type": "error",
                    "message": "Invalid action.",
                    "allowedActions": ["send_message", "typing", "mark_read"],
                }
            )

    async def chat_message(self, event):
        await self.send_json(
            {
                "type": "message",
                "message": event["message"],
                "clientMessageId": event.get("clientMessageId"),
            }
        )

    async def chat_typing(self, event):
        if str(event["user"]["id"]) != str(self.user.id):
            await self.send_json(
                {
                    "type": "typing",
                    "user": event["user"],
                    "isTyping": event["isTyping"],
                }
            )

    async def chat_read(self, event):
        await self.send_json(
            {
                "type": "read_receipt",
                "reader": event["reader"],
                "data": event["data"],
            }
        )

    async def chat_presence(self, event):
        if event.get("user") and str(event["user"]["id"]) != str(self.user.id):
            await self.send_json(
                {
                    "type": "presence",
                    "event": event["event"],
                    "user": event["user"],
                }
            )

    @database_sync_to_async
    def can_access_conversation(self):
        conversation = (
            ChatConversation.objects
            .select_related("customer", "admin")
            .filter(id=self.conversation_id)
            .first()
        )

        if not conversation:
            return False

        if conversation.customer_id == self.user.id:
            return True

        if is_admin_user(self.user):
            if not conversation.admin_id:
                conversation.admin = self.user
                conversation.save(update_fields=["admin", "updated_at"])
            return True

        return False

    @database_sync_to_async
    def create_message(self, message_text):
        conversation = ChatConversation.objects.select_related("customer", "admin").get(
            id=self.conversation_id
        )

        message = ChatMessage.objects.create(
            conversation=conversation,
            sender=self.user,
            message_type=ChatMessage.MESSAGE_TEXT,
            message=message_text,
        )

        conversation.last_message = message_text[:500]
        conversation.last_message_at = message.created_at
        conversation.save(update_fields=["last_message", "last_message_at", "updated_at"])

        return build_message_payload(message)

    @database_sync_to_async
    def mark_messages_read(self):
        now = timezone.now()

        conversation = ChatConversation.objects.get(id=self.conversation_id)

        if is_admin_user(self.user):
            conversation.admin_last_read_at = now
        else:
            conversation.customer_last_read_at = now

        conversation.save(update_fields=["admin_last_read_at", "customer_last_read_at", "updated_at"])

        updated_count = (
            ChatMessage.objects
            .filter(conversation=conversation, read_at__isnull=True)
            .exclude(sender=self.user)
            .update(read_at=now)
        )

        return {
            "conversationId": str(conversation.id),
            "readAt": now.isoformat(),
            "updatedCount": updated_count,
        }


def build_message_payload(message):
    attachment_url = None

    if message.attachment:
        try:
            attachment_url = message.attachment.url
        except Exception:
            attachment_url = None

    return {
        "id": str(message.id),
        "conversationId": str(message.conversation_id),
        "sender": user_payload(message.sender) if message.sender else None,
        "messageType": message.message_type,
        "message": message.message,
        "attachmentUrl": attachment_url,
        "readAt": message.read_at.isoformat() if message.read_at else None,
        "createdAt": message.created_at.isoformat() if message.created_at else None,
    }