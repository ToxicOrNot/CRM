from django.urls import path

from apps.clients.views import (
    ClientArchiveListView,
    ClientArchiveView,
    ClientCreateView,
    ClientDetailView,
    ClientListView,
    ClientRestoreView,
    ClientUpdateView,
    ContactParseConfirmView,
    ContactParseView,
)


app_name = "clients"

urlpatterns = [
    path("", ClientListView.as_view(), name="list"),
    path("archive/", ClientArchiveListView.as_view(), name="archive"),
    path("create/", ClientCreateView.as_view(), name="create"),
    path("parse/", ContactParseView.as_view(), name="parse"),
    path("parse/confirm/", ContactParseConfirmView.as_view(), name="parse_confirm"),
    path("<int:pk>/", ClientDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", ClientUpdateView.as_view(), name="edit"),
    path("<int:pk>/archive/", ClientArchiveView.as_view(), name="archive_item"),
    path("<int:pk>/restore/", ClientRestoreView.as_view(), name="restore"),
]
