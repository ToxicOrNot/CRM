from django.urls import path

from apps.tasks.views import (
    ArchiveTaskListView,
    MyTaskListView,
    TaskAttachmentArchiveView,
    TaskCompleteView,
    TaskCreateView,
    TaskDetailView,
    TaskListView,
    TaskUndoCompleteView,
    TaskUnarchiveView,
    TaskUpdateView,
)


app_name = "tasks"

urlpatterns = [
    path("", TaskListView.as_view(), name="list"),
    path("my/", MyTaskListView.as_view(), name="my"),
    path("archive/", ArchiveTaskListView.as_view(), name="archive"),
    path("create/", TaskCreateView.as_view(), name="create"),
    path("<int:pk>/", TaskDetailView.as_view(), name="detail"),
    path("<int:pk>/edit/", TaskUpdateView.as_view(), name="edit"),
    path("<int:pk>/complete/", TaskCompleteView.as_view(), name="complete"),
    path("<int:pk>/undo-complete/", TaskUndoCompleteView.as_view(), name="undo_complete"),
    path("<int:pk>/unarchive/", TaskUnarchiveView.as_view(), name="unarchive"),
    path("<int:pk>/attachments/download/", TaskAttachmentArchiveView.as_view(), name="download_attachments"),
]
