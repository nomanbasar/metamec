from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils import timezone
from django.utils.timesince import timesince

from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserNotification
from .utils import create_notification

User = get_user_model()


def api_response(request, success=True, message="", data=None, meta=None, status_code=status.HTTP_200_OK):
    return Response(
        {
            "success": success,
            "message": message,
            "meta": meta or {},
            "data": {} if data is None else data,
            "requestId": request.headers.get("X-Request-ID", "") if request else "",
        },
        status=status_code,
    )


def is_admin_user(user):
    return bool(
        user
        and user.is_authenticated
        and (
            getattr(user, "is_staff", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "role", "") == "admin"
        )
    )


def to_int(value, default=1):
    try:
        return int(value)
    except Exception:
        return default


def user_email(user):
    return (
        getattr(user, "email_address", None)
        or getattr(user, "email", None)
        or ""
    )


def user_name(user):
    return (
        getattr(user, "full_name", None)
        or getattr(user, "name", None)
        or user_email(user)
        or str(user)
    )


def notification_payload(notification):
    created_at = timezone.localtime(notification.created_at)

    return {
        "id": str(notification.id),
        "title": notification.title,
        "message": notification.message,
        "type": notification.notification_type,
        "typeLabel": notification.get_notification_type_display(),
        "priority": notification.priority,
        "priorityLabel": notification.get_priority_display(),
        "isRead": notification.is_read,
        "readAt": notification.read_at.isoformat() if notification.read_at else None,
        "createdAt": created_at.isoformat(),
        "timeAgo": f"{timesince(created_at)} ago",
        "action": {
            "screen": notification.action_screen,
            "api": notification.action_api,
            "objectId": notification.object_id,
            "objectType": notification.object_type,
        },
        "metadata": notification.metadata or {},
    }


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        queryset = UserNotification.objects.filter(user=request.user)

        read_status = request.query_params.get("status")
        notification_type = request.query_params.get("type")
        search = request.query_params.get("search")

        if read_status == "unread":
            queryset = queryset.filter(is_read=False)

        if read_status == "read":
            queryset = queryset.filter(is_read=True)

        if notification_type:
            queryset = queryset.filter(notification_type=notification_type)

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(message__icontains=search)
                | Q(object_id__icontains=search)
                | Q(object_type__icontains=search)
            )

        total_count = queryset.count()
        unread_count = UserNotification.objects.filter(user=request.user, is_read=False).count()

        page = max(to_int(request.query_params.get("page"), 1), 1)
        limit = max(min(to_int(request.query_params.get("limit"), 20), 100), 1)

        start = (page - 1) * limit
        end = start + limit

        items = queryset.order_by("-created_at")[start:end]

        return api_response(
            request,
            success=True,
            message="Notifications fetched successfully",
            data=[notification_payload(item) for item in items],
            meta={
                "unreadCount": unread_count,
                "total": total_count,
                "page": page,
                "limit": limit,
                "hasNext": end < total_count,
                "filters": {
                    "status": read_status or "",
                    "type": notification_type or "",
                    "search": search or "",
                },
            },
            status_code=status.HTTP_200_OK,
        )


class NotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, notification_id):
        notification = UserNotification.objects.filter(
            id=notification_id,
            user=request.user,
        ).first()

        if not notification:
            return api_response(
                request,
                success=False,
                message="Notification not found",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        notification.mark_as_read()

        return api_response(
            request,
            success=True,
            message="Notification marked as read successfully",
            data=notification_payload(notification),
            status_code=status.HTTP_200_OK,
        )


class NotificationMarkAllReadView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request):
        now = timezone.now()

        updated_count = UserNotification.objects.filter(
            user=request.user,
            is_read=False,
        ).update(
            is_read=True,
            read_at=now,
            updated_at=now,
        )

        return api_response(
            request,
            success=True,
            message="All notifications marked as read successfully",
            data={
                "updatedCount": updated_count,
            },
            status_code=status.HTTP_200_OK,
        )


class AdminNotificationSendView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def post(self, request):
        if not is_admin_user(request.user):
            return api_response(
                request,
                success=False,
                message="Admin permission required",
                data={},
                status_code=status.HTTP_403_FORBIDDEN,
            )

        user_id = request.data.get("user_id") or request.data.get("userId")
        email_address = request.data.get("email_address") or request.data.get("email")

        target_user = None

        if user_id:
            target_user = User.objects.filter(id=user_id, is_active=True).first()

        if not target_user and email_address:
            target_user = User.objects.filter(
                Q(email_address__iexact=email_address) | Q(email__iexact=email_address),
                is_active=True,
            ).first()

        if not target_user:
            return api_response(
                request,
                success=False,
                message="Target user not found. Send user_id or email_address.",
                data={},
                status_code=status.HTTP_404_NOT_FOUND,
            )

        title = request.data.get("title")
        message = request.data.get("message")

        if not title or not message:
            return api_response(
                request,
                success=False,
                message="title and message are required",
                data={
                    "title": ["This field is required."],
                    "message": ["This field is required."],
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        notification = create_notification(
            user=target_user,
            title=title,
            message=message,
            notification_type=request.data.get("type") or request.data.get("notification_type") or UserNotification.TYPE_GENERAL,
            priority=request.data.get("priority") or UserNotification.PRIORITY_NORMAL,
            action_screen=request.data.get("action_screen") or request.data.get("actionScreen"),
            action_api=request.data.get("action_api") or request.data.get("actionApi"),
            object_id=request.data.get("object_id") or request.data.get("objectId"),
            object_type=request.data.get("object_type") or request.data.get("objectType"),
            metadata=request.data.get("metadata") or {},
        )

        if not notification:
            return api_response(
                request,
                success=False,
                message="Notification create failed",
                data={},
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return api_response(
            request,
            success=True,
            message="Notification sent successfully",
            data=notification_payload(notification),
            status_code=status.HTTP_201_CREATED,
        )