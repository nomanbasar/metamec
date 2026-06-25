from django.urls import path

from .views import (
    ChatAssignAdminView,
    ChatConversationDetailView,
    ChatConversationListCreateView,
    ChatMarkReadView,
    ChatMessagesView,
)


urlpatterns = [
    path(
        "chat/conversations/",
        ChatConversationListCreateView.as_view(),
        name="chat_conversation_list_create",
    ),
    path(
        "chat/conversations/<uuid:conversation_id>/",
        ChatConversationDetailView.as_view(),
        name="chat_conversation_detail",
    ),
    path(
        "chat/conversations/<uuid:conversation_id>/messages/",
        ChatMessagesView.as_view(),
        name="chat_messages",
    ),
    path(
        "chat/conversations/<uuid:conversation_id>/read/",
        ChatMarkReadView.as_view(),
        name="chat_mark_read",
    ),
    path(
        "chat/conversations/<uuid:conversation_id>/assign/",
        ChatAssignAdminView.as_view(),
        name="chat_assign_admin",
    ),
]