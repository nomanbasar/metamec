from django.urls import path

from .views import (
    AdminNotificationSendView,
    NotificationListView,
    NotificationMarkAllReadView,
    NotificationReadView,
)


urlpatterns = [
    path(
        "notifications/",
        NotificationListView.as_view(),
        name="notifications_list",
    ),
    path(
        "notifications/<uuid:notification_id>/read/",
        NotificationReadView.as_view(),
        name="notification_read",
    ),
    path(
        "notifications/mark-all-read/",
        NotificationMarkAllReadView.as_view(),
        name="notifications_mark_all_read",
    ),

    # Admin/manual testing API
    path(
        "admin/notifications/send/",
        AdminNotificationSendView.as_view(),
        name="admin_notification_send",
    ),
]