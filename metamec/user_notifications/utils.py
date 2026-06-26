import logging

from django.contrib.auth import get_user_model

from .models import UserNotification

logger = logging.getLogger(__name__)
User = get_user_model()


def create_notification(
    user,
    title,
    message,
    notification_type=UserNotification.TYPE_GENERAL,
    priority=UserNotification.PRIORITY_NORMAL,
    action_screen=None,
    action_api=None,
    object_id=None,
    object_type=None,
    metadata=None,
):
    """
    Safe notification creator.
    Existing flow break হবে না, কারণ error হলে None return করবে।
    """
    try:
        if not user:
            return None

        return UserNotification.objects.create(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority,
            action_screen=action_screen,
            action_api=action_api,
            object_id=str(object_id) if object_id else None,
            object_type=object_type,
            metadata=metadata or {},
        )
    except Exception as exc:
        logger.exception("Notification create failed: %s", exc)
        return None


def notify_admins(
    title,
    message,
    notification_type=UserNotification.TYPE_GENERAL,
    priority=UserNotification.PRIORITY_NORMAL,
    action_screen=None,
    action_api=None,
    object_id=None,
    object_type=None,
    metadata=None,
):
    """
    Adminদের notification দিতে চাইলে use করবেন।
    """
    try:
        admins = User.objects.filter(is_active=True).filter(
            is_staff=True
        )

        created = []

        for admin_user in admins:
            item = create_notification(
                user=admin_user,
                title=title,
                message=message,
                notification_type=notification_type,
                priority=priority,
                action_screen=action_screen,
                action_api=action_api,
                object_id=object_id,
                object_type=object_type,
                metadata=metadata,
            )
            if item:
                created.append(item)

        return created
    except Exception as exc:
        logger.exception("Admin notification failed: %s", exc)
        return []