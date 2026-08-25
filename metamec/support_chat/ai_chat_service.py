import logging
from datetime import time
from threading import Lock
from zoneinfo import ZoneInfo

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from user_notifications.events import notify_chat_message

from .models import ChatConversation, ChatMessage


logger = logging.getLogger(__name__)
User = get_user_model()


_engine = None
_engine_lock = Lock()


def _get_engine():
    """
    Create RAGChatEngine only once per Django process.

    rag_engine itself remains completely unchanged.
    """
    global _engine

    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from rag_engine import RAGChatEngine

                _engine = RAGChatEngine()

    return _engine


def _parse_time(value, default):
    try:
        return time.fromisoformat(str(value))
    except (TypeError, ValueError):
        return time.fromisoformat(default)


def _get_workdays():
    raw = str(
        getattr(
            settings,
            "AI_CHAT_WORKDAYS",
            "0,1,2,3,4",
        )
    )

    days = set()

    for item in raw.split(","):
        item = item.strip()

        if item.isdigit():
            day = int(item)

            if 0 <= day <= 6:
                days.add(day)

    return days or {0, 1, 2, 3, 4}


def is_after_hours():
    """
    Monday = 0
    Tuesday = 1
    ...
    Sunday = 6
    """

    if getattr(
        settings,
        "AI_CHAT_FORCE_AFTER_HOURS",
        False,
    ):
        return True

    if getattr(
        settings,
        "AI_CHAT_FORCE_OFFICE_HOURS",
        False,
    ):
        return False

    timezone_name = getattr(
        settings,
        "AI_CHAT_TIMEZONE",
        "Europe/London",
    )

    try:
        current_datetime = timezone.now().astimezone(
            ZoneInfo(timezone_name)
        )
    except Exception:
        logger.exception(
            "Invalid AI_CHAT_TIMEZONE: %s",
            timezone_name,
        )
        return False

    if current_datetime.weekday() not in _get_workdays():
        return True

    office_start = _parse_time(
        getattr(
            settings,
            "AI_CHAT_OFFICE_START",
            "09:00",
        ),
        "09:00",
    )

    office_end = _parse_time(
        getattr(
            settings,
            "AI_CHAT_OFFICE_END",
            "17:00",
        ),
        "17:00",
    )

    current_time = current_datetime.time().replace(
        tzinfo=None
    )

    if office_start <= office_end:
        office_is_open = (
            office_start
            <= current_time
            < office_end
        )
    else:
        office_is_open = (
            current_time >= office_start
            or current_time < office_end
        )

    return not office_is_open


def is_ai_user(user):
    if not user:
        return False

    email = str(
        getattr(
            user,
            "email_address",
            "",
        )
        or ""
    ).strip().lower()

    ai_email = str(
        getattr(
            settings,
            "AI_CHAT_USER_EMAIL",
            "ai-assistant@dragonfinance.local",
        )
    ).strip().lower()

    return email == ai_email


def _get_ai_user():
    """
    Uses existing User model.
    No model change and no migration required.
    """

    email = str(
        getattr(
            settings,
            "AI_CHAT_USER_EMAIL",
            "ai-assistant@dragonfinance.local",
        )
    ).strip().lower()

    name = str(
        getattr(
            settings,
            "AI_CHAT_USER_NAME",
            "Dragon Finance AI Assistant",
        )
    ).strip()

    user = User.objects.filter(
        email_address=email
    ).first()

    if user:
        return user

    user = User.objects.create(
        email_address=email,
        full_name=name,
        role="admin",
        is_active=True,
        is_staff=False,
        is_email_verified=True,
    )

    user.set_unusable_password()
    user.save(
        update_fields=["password"]
    )

    return user


def _build_chat_history(
    conversation,
    current_message_id=None,
):
    limit = getattr(
        settings,
        "AI_CHAT_HISTORY_LIMIT",
        12,
    )

    queryset = (
        ChatMessage.objects
        .select_related("sender")
        .filter(
            conversation=conversation,
            message_type=ChatMessage.MESSAGE_TEXT,
        )
        .exclude(message__isnull=True)
        .exclude(message="")
    )

    if current_message_id:
        queryset = queryset.exclude(
            id=current_message_id
        )

    messages = list(
        queryset.order_by(
            "-created_at"
        )[:limit]
    )

    messages.reverse()

    history = []

    for item in messages:
        content = str(
            item.message or ""
        ).strip()

        if not content:
            continue

        if item.sender_id == conversation.customer_id:
            role = "user"
        else:
            role = "assistant"

        history.append(
            {
                "role": role,
                "content": content,
            }
        )

    return history


def should_ai_respond(
    conversation,
    sender,
    message_text,
    has_attachment=False,
):
    if not getattr(
        settings,
        "AI_CHAT_ENABLED",
        True,
    ):
        return False

    if not conversation:
        return False

    if not sender:
        return False

    if (
        conversation.status
        != ChatConversation.STATUS_OPEN
    ):
        return False

    # Only customer messages can trigger AI.
    if sender.id != conversation.customer_id:
        return False

    # Current supplied RAG agent handles text questions.
    if has_attachment:
        return False

    if not str(
        message_text or ""
    ).strip():
        return False

    return is_after_hours()


def _user_payload(user):
    if not user:
        return None

    return {
        "id": str(user.id),
        "name": (
            getattr(user, "full_name", None)
            or getattr(user, "email_address", None)
            or "User"
        ),
        "email": (
            getattr(user, "email_address", None)
            or ""
        ),
        "role": getattr(
            user,
            "role",
            None,
        ),
        "isAdmin": bool(
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or str(
                getattr(user, "role", "")
            ).lower() == "admin"
        ),
        "isSupportStaff": (
            str(
                getattr(
                    user,
                    "role",
                    "",
                )
            ).lower()
            == "support_staff"
        ),
        "isAI": is_ai_user(user),
    }


def _message_payload(message):
    attachment_url = None

    if message.attachment:
        try:
            attachment_url = message.attachment.url
        except Exception:
            attachment_url = None

    return {
        "id": str(message.id),
        "conversationId": str(
            message.conversation_id
        ),
        "sender": _user_payload(
            message.sender
        ),
        "messageType": message.message_type,
        "message": message.message,
        "attachmentUrl": attachment_url,
        "readAt": (
            message.read_at.isoformat()
            if message.read_at
            else None
        ),
        "createdAt": (
            message.created_at.isoformat()
            if message.created_at
            else None
        ),
    }


def broadcast_ai_message(message):
    """
    Broadcast AI message to the same existing WebSocket group.
    """

    channel_layer = get_channel_layer()

    if channel_layer is None:
        return

    async_to_sync(
        channel_layer.group_send
    )(
        f"chat_{message.conversation_id}",
        {
            "type": "chat.message",
            "message": _message_payload(
                message
            ),
        },
    )


def maybe_generate_ai_reply(
    conversation,
    sender,
    message_text,
    current_message_id=None,
    has_attachment=False,
    broadcast=True,
):
    """
    Returns ChatMessage if AI replied.
    Returns None when AI should not reply or when AI fails.

    The customer's existing message is never rolled back.
    """

    if not should_ai_respond(
        conversation=conversation,
        sender=sender,
        message_text=message_text,
        has_attachment=has_attachment,
    ):
        return None

    try:
        engine = _get_engine()

        history = _build_chat_history(
            conversation=conversation,
            current_message_id=current_message_id,
        )

        response = engine.answer(
            query=str(
                message_text
            ).strip(),
            chat_history=history,
        )

        answer = str(
            response.answer or ""
        ).strip()

        if not answer:
            logger.warning(
                "AI returned an empty response "
                "for conversation %s",
                conversation.id,
            )
            return None

        ai_user = _get_ai_user()

        ai_message = ChatMessage.objects.create(
            conversation=conversation,
            sender=ai_user,
            message_type=ChatMessage.MESSAGE_TEXT,
            message=answer,
        )

        conversation.last_message = answer[:500]
        conversation.last_message_at = (
            ai_message.created_at
        )

        conversation.save(
            update_fields=[
                "last_message",
                "last_message_at",
                "updated_at",
            ]
        )

        # Existing notification system:
        # AI -> customer is treated as a support message.
        notify_chat_message(ai_message)

        if broadcast:
            broadcast_ai_message(ai_message)

        return ai_message

    except Exception:
        logger.exception(
            "AI reply failed for conversation %s",
            getattr(
                conversation,
                "id",
                None,
            ),
        )

        return None