from __future__ import annotations

from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Case, F, IntegerField, QuerySet, When
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseNotFound
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from apps.tasks.forms import TaskForm
from apps.tasks.models import Task, TaskAttachment, TaskPriority, TaskStatus


TASK_SORT_LABELS = {
    "title": "Название",
    "assignee": "Исполнитель",
    "priority": "Приоритет",
    "due_at": "Срок исполнения",
    "created_at": "Дата начала",
}

TASK_SORT_DEFAULT_DIRECTIONS = {
    "title": "asc",
    "assignee": "asc",
    "priority": "desc",
    "due_at": "asc",
    "created_at": "desc",
}

TASK_PRIORITY_ORDER = Case(
    When(priority=TaskPriority.LOW, then=1),
    When(priority=TaskPriority.NORMAL, then=2),
    When(priority=TaskPriority.HIGH, then=3),
    When(priority=TaskPriority.URGENT, then=4),
    default=0,
    output_field=IntegerField(),
)


def save_task_attachments(
    task: Task,
    uploaded_files: Iterable[UploadedFile],
    uploaded_by: object,
) -> None:
    for uploaded_file in uploaded_files:
        TaskAttachment.objects.create(
            task=task,
            file=uploaded_file,
            original_name=uploaded_file.name,
            uploaded_by=uploaded_by,
        )


class TaskListView(LoginRequiredMixin, ListView):
    model = Task
    template_name = "tasks/task_list.html"
    context_object_name = "tasks"
    paginate_by = 20
    page_title = "Все задачи"
    is_archive_view = False

    def get_queryset(self):
        queryset = (
            Task.objects.select_related("creator", "assignee", "order")
            .prefetch_related("attachments", "attachments__uploaded_by")
            .filter(archived=False)
            .order_by("-created_at")
        )
        assignee = self.request.GET.get("assignee")
        overdue_only = self.request.GET.get("overdue") == "1"

        if assignee:
            queryset = queryset.filter(assignee_id=assignee)
        if overdue_only:
            queryset = queryset.overdue()

        return self.apply_sorting(queryset)

    def apply_sorting(self, queryset: QuerySet[Task]) -> QuerySet[Task]:
        sort = self.request.GET.get("sort", "")
        direction = self.request.GET.get("direction", "")

        if sort not in TASK_SORT_LABELS or direction not in {"asc", "desc"}:
            return queryset

        descending = direction == "desc"
        if sort == "priority":
            order_expression = (
                F("priority_order").desc(nulls_last=True)
                if descending
                else F("priority_order").asc(nulls_last=True)
            )
            return queryset.annotate(priority_order=TASK_PRIORITY_ORDER).order_by(
                order_expression,
                "-created_at",
            )
        if sort == "assignee":
            fields = ("assignee__last_name", "assignee__first_name", "assignee__username")
            ordering = [f"-{field}" if descending else field for field in fields]
            return queryset.order_by(*ordering, "-created_at")
        if sort in {"due_at", "created_at"}:
            order_expression = (
                F(sort).desc(nulls_last=True)
                if descending
                else F(sort).asc(nulls_last=True)
            )
            return queryset.order_by(order_expression, "-created_at")

        return queryset.order_by("-title" if descending else "title", "-created_at")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        User = get_user_model()
        context["page_title"] = self.page_title
        context["users"] = User.objects.filter(is_active=True).order_by(
            "last_name",
            "first_name",
            "username",
        )
        context["filters"] = {
            "assignee": self.request.GET.get("assignee", ""),
            "overdue": self.request.GET.get("overdue") == "1",
        }
        context["sort_links"] = self.get_sort_links()
        context["is_archive_view"] = self.is_archive_view
        context["editable_task_ids"] = {
            task.pk for task in context["tasks"] if task.can_be_edited_by(self.request.user)
        }
        context["completable_task_ids"] = {
            task.pk
            for task in context["tasks"]
            if task.can_be_edited_by(self.request.user)
            and task.status not in Task.TERMINAL_STATUSES
        }
        return context

    def get_sort_links(self) -> dict[str, dict[str, str | bool]]:
        current_sort = self.request.GET.get("sort", "")
        current_direction = self.request.GET.get("direction", "")
        links: dict[str, dict[str, str | bool]] = {}

        for field, label in TASK_SORT_LABELS.items():
            is_active = current_sort == field and current_direction in {"asc", "desc"}
            if is_active:
                next_direction = "desc" if current_direction == "asc" else "asc"
                indicator = "↑" if current_direction == "asc" else "↓"
            else:
                next_direction = TASK_SORT_DEFAULT_DIRECTIONS[field]
                indicator = ""

            params = self.request.GET.copy()
            params.pop("page", None)
            params["sort"] = field
            params["direction"] = next_direction
            links[field] = {
                "label": label,
                "url": f"?{params.urlencode()}",
                "active": is_active,
                "indicator": indicator,
            }

        return links


class MyTaskListView(TaskListView):
    page_title = "Мои задачи"

    def get_queryset(self):
        return super().get_queryset().filter(assignee=self.request.user)


class ArchiveTaskListView(TaskListView):
    page_title = "Архив"
    is_archive_view = True

    def get_queryset(self):
        queryset = (
            Task.objects.select_related("creator", "assignee", "order")
            .prefetch_related("attachments", "attachments__uploaded_by")
            .filter(archived=True)
            .order_by("-updated_at")
        )
        assignee = self.request.GET.get("assignee")
        overdue_only = self.request.GET.get("overdue") == "1"

        if assignee:
            queryset = queryset.filter(assignee_id=assignee)
        if overdue_only:
            queryset = queryset.overdue()

        return self.apply_sorting(queryset)


class TaskDetailView(LoginRequiredMixin, DetailView):
    model = Task
    template_name = "tasks/task_detail.html"
    context_object_name = "task"

    def get_queryset(self):
        return Task.objects.select_related("creator", "assignee", "order").prefetch_related(
            "attachments",
            "attachments__uploaded_by",
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["can_edit"] = self.object.can_be_edited_by(self.request.user)
        return context


class TaskCreateView(LoginRequiredMixin, CreateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/task_form.html"
    success_url = reverse_lazy("tasks:list")

    def get_initial(self) -> dict[str, object]:
        initial = super().get_initial()
        order_id = self.request.GET.get("order")
        if order_id:
            initial["order"] = order_id
        return initial

    def get_success_url(self) -> str:
        if self.object.order_id:
            return reverse("orders:detail", kwargs={"pk": self.object.order_id})
        return str(self.success_url)

    def form_valid(self, form: TaskForm):
        form.instance.creator = self.request.user
        response = super().form_valid(form)
        save_task_attachments(
            task=self.object,
            uploaded_files=self.request.FILES.getlist("attachments"),
            uploaded_by=self.request.user,
        )
        messages.success(self.request, "Задача создана.")
        return response

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Создать задачу"
        context["submit_label"] = "Создать"
        return context


class TaskUpdateView(LoginRequiredMixin, UserPassesTestMixin, UpdateView):
    model = Task
    form_class = TaskForm
    template_name = "tasks/task_form.html"

    def get_queryset(self):
        return Task.objects.select_related("creator", "assignee", "order").prefetch_related(
            "attachments",
            "attachments__uploaded_by",
        )

    def test_func(self) -> bool:
        task = self.get_object()
        return task.can_be_edited_by(self.request.user)

    def get_success_url(self) -> str:
        return self.object.get_absolute_url()

    def form_valid(self, form: TaskForm):
        response = super().form_valid(form)
        save_task_attachments(
            task=self.object,
            uploaded_files=self.request.FILES.getlist("attachments"),
            uploaded_by=self.request.user,
        )
        messages.success(self.request, "Задача обновлена.")
        return response

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Редактировать задачу"
        context["submit_label"] = "Сохранить"
        context["attachments"] = self.object.attachments.select_related("uploaded_by")
        return context


class TaskCompleteView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        task = get_object_or_404(Task.objects.select_related("creator", "assignee"), pk=pk)
        if not task.can_be_edited_by(request.user):
            return HttpResponseForbidden("Недостаточно прав для изменения задачи.")

        request.session["task_completion_undo"] = {
            "task_id": task.pk,
            "title": task.title,
            "previous_status": task.status,
            "previous_archived": task.archived,
        }
        task.set_status(TaskStatus.COMPLETED)
        task.archived = True
        task.save()
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("tasks:list")


class TaskUndoCompleteView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        undo_data = request.session.get("task_completion_undo")
        if not undo_data or undo_data.get("task_id") != pk:
            return redirect(self.get_success_url())

        task = get_object_or_404(Task.objects.select_related("creator", "assignee"), pk=pk)
        if not task.can_be_edited_by(request.user):
            return HttpResponseForbidden("Недостаточно прав для изменения задачи.")

        previous_status = undo_data.get("previous_status", TaskStatus.NEW)
        if previous_status not in TaskStatus.values:
            previous_status = TaskStatus.NEW

        task.set_status(previous_status)
        task.archived = bool(undo_data.get("previous_archived", False))
        task.save()
        request.session.pop("task_completion_undo", None)
        messages.info(request, f"Отметка выполнения задачи «{task.title}» отменена.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("tasks:list")


class TaskUnarchiveView(LoginRequiredMixin, View):
    def post(self, request, pk: int):
        task = get_object_or_404(Task.objects.select_related("creator", "assignee"), pk=pk)
        if not task.can_be_edited_by(request.user):
            return HttpResponseForbidden("Недостаточно прав для изменения задачи.")

        task.unarchive()
        task.save()
        messages.success(request, f"Задача «{task.title}» убрана из архива.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("tasks:archive")


class TaskAttachmentArchiveView(LoginRequiredMixin, View):
    def get(self, request, pk: int):
        task = get_object_or_404(
            Task.objects.prefetch_related("attachments"),
            pk=pk,
        )
        attachments = list(task.attachments.all())
        if not attachments:
            return HttpResponseNotFound("У задачи нет прикрепленных файлов.")

        archive = BytesIO()
        used_names: set[str] = set()
        with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
            for attachment in attachments:
                if not attachment.file:
                    continue
                file_name = attachment.file.name
                if not attachment.file.storage.exists(file_name):
                    continue
                archive_name = self.get_unique_archive_name(
                    attachment.original_name or Path(file_name).name,
                    used_names,
                )
                with attachment.file.open("rb") as source:
                    zip_file.writestr(archive_name, source.read())

        if not used_names:
            return HttpResponseNotFound("Файлы задачи не найдены на сервере.")

        archive.seek(0)
        response = HttpResponse(archive.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="task-{task.pk}-files.zip"'
        return response

    @staticmethod
    def get_unique_archive_name(file_name: str, used_names: set[str]) -> str:
        clean_name = Path(file_name).name or "file"
        if clean_name not in used_names:
            used_names.add(clean_name)
            return clean_name

        stem = Path(clean_name).stem or "file"
        suffix = Path(clean_name).suffix
        counter = 2
        while True:
            candidate = f"{stem}-{counter}{suffix}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            counter += 1
