from django.urls import path

from .views import (
    AdminApplicationDetailView,
    AdminApplicationDocumentsView,
    AdminApplicationNotesView,
    AdminApplicationsListView,
    AdminApplicationStatusUpdateView,
    AdminApplicationTimelineView,
    AdminDocumentStatusUpdateView,
)


urlpatterns = [
    path(
        "admin/applications/",
        AdminApplicationsListView.as_view(),
        name="admin_applications_list",
    ),
    path(
        "admin/applications/<uuid:pk>/",
        AdminApplicationDetailView.as_view(),
        name="admin_application_detail",
    ),
    path(
        "admin/applications/<uuid:pk>/documents/",
        AdminApplicationDocumentsView.as_view(),
        name="admin_application_documents",
    ),
    path(
        "admin/documents/<uuid:document_id>/status/",
        AdminDocumentStatusUpdateView.as_view(),
        name="admin_document_status_update",
    ),
    path(
        "admin/applications/<uuid:pk>/status/",
        AdminApplicationStatusUpdateView.as_view(),
        name="admin_application_status_update",
    ),
    path(
        "admin/applications/<uuid:pk>/notes/",
        AdminApplicationNotesView.as_view(),
        name="admin_application_notes",
    ),
    path(
        "admin/applications/<uuid:pk>/timeline/",
        AdminApplicationTimelineView.as_view(),
        name="admin_application_timeline",
    ),
]