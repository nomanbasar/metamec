from django.urls import path

from .views import (
    AdminSupportAgentAvailabilityView,
    AdminSupportAppointmentListView,
    AdminSupportAppointmentStatusView,
    AdminSupportAvailabilityDetailView,
    AdminSupportCaseManagerListCreateView,
    AdminSupportCaseManagerDetailView,
    ChatAssignAdminView,
    ChatConversationDetailView,
    ChatConversationListCreateView,
    ChatMarkReadView,
    ChatMessagesView,
    MySupportAppointmentListView,
    SupportAppointmentCancelView,
    SupportAppointmentListCreateView,
    SupportAppointmentRescheduleView,
    SupportCaseManagerListView,
    SupportCaseManagerSlotsView,
    SupportBookCallView,
    StaffProfileView,
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

    path(
        "admin/support/availability/<uuid:availability_id>/",
        AdminSupportAvailabilityDetailView.as_view(),
        name="admin_support_availability_detail",
    ),

    path(
        "admin/support/case-managers/<uuid:manager_id>/",
        AdminSupportCaseManagerDetailView.as_view(),
        name="admin_support_case_manager_detail",
    ),

    # Customer Book a Call APIs
    path(
        "support/case-managers/",
        SupportCaseManagerListView.as_view(),
        name="support_case_managers",
    ),
    path(
        "support/case-managers/<uuid:manager_id>/slots/",
        SupportCaseManagerSlotsView.as_view(),
        name="support_case_manager_slots",
    ),
    path(
        "support/appointments/",
        SupportAppointmentListCreateView.as_view(),
        name="support_appointment_create",
    ),
    path(
        "support/appointments/my/",
        MySupportAppointmentListView.as_view(),
        name="my_support_appointments",
    ),
    path(
        "support/appointments/<uuid:appointment_id>/cancel/",
        SupportAppointmentCancelView.as_view(),
        name="support_appointment_cancel",
    ),
    path(
        "support/appointments/<uuid:appointment_id>/reschedule/",
        SupportAppointmentRescheduleView.as_view(),
        name="support_appointment_reschedule",
    ),

    # Admin Book a Call APIs
    path(
        "admin/support/case-managers/",
        AdminSupportCaseManagerListCreateView.as_view(),
        name="admin_support_case_managers",
    ),
    path(
        "admin/support/case-managers/<uuid:manager_id>/availability/",
        AdminSupportAgentAvailabilityView.as_view(),
        name="admin_support_agent_availability",
    ),
    path(
        "admin/support/appointments/",
        AdminSupportAppointmentListView.as_view(),
        name="admin_support_appointments",
    ),
    path(
        "admin/support/appointments/<uuid:appointment_id>/status/",
        AdminSupportAppointmentStatusView.as_view(),
        name="admin_support_appointment_status",
    ),
    path(
        "support/book-call/",
        SupportBookCallView.as_view(),
        name="support_book_call",
    ),


    path("staff/profile/",StaffProfileView.as_view(), name="staff_profile"),
]