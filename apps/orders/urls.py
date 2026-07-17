from django.urls import path

from apps.orders.views import (
    OrderArchiveListView,
    OrderArchiveView,
    OrderCreateView,
    OrderDetailView,
    OrderListView,
    OrderQuickUpdateView,
    OrderRestoreView,
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
    path("<int:pk>/archive/", OrderArchiveView.as_view(), name="archive_item"),
    path("<int:pk>/restore/", OrderRestoreView.as_view(), name="restore"),
]
