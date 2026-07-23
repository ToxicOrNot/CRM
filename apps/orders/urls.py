from django.urls import path

from apps.orders.views import (
    OrderAttachmentArchiveView,
    OrderAttachmentDeleteView,
    OrderAttachmentPreviewView,
    OrderArchiveListView,
    OrderArchiveView,
    OrderCreateView,
    OrderDetailView,
    OrderListView,
    OrderQuickUpdateView,
    OrderRestoreView,
    OrderResolveClientView,
    OrderUpdateView,
)


app_name = "orders"

urlpatterns = [
    path("", OrderListView.as_view(), name="list"),
    path("archive/", OrderArchiveListView.as_view(), name="archive"),
    path("create/", OrderCreateView.as_view(), name="create"),
    path("<int:pk>/", OrderDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", OrderUpdateView.as_view(), name="edit"),
    path("<int:pk>/quick-update/", OrderQuickUpdateView.as_view(), name="quick_update"),
    path("<int:pk>/resolve-client/", OrderResolveClientView.as_view(), name="resolve_client"),
    path("<int:pk>/attachments/download/", OrderAttachmentArchiveView.as_view(), name="download_attachments"),
    path("attachments/<int:pk>/preview/", OrderAttachmentPreviewView.as_view(), name="attachment_preview"),
    path("attachments/<int:pk>/delete/", OrderAttachmentDeleteView.as_view(), name="delete_attachment"),
    path("<int:pk>/archive/", OrderArchiveView.as_view(), name="archive_item"),
    path("<int:pk>/restore/", OrderRestoreView.as_view(), name="restore"),
]
