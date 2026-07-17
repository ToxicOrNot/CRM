from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


def task_attachment_upload_to(instance: "TaskAttachment", filename: str) -> str:
    return f"tasks/{instance.task_id}/attachments/{filename}"


class TaskStatus(models.TextChoices):
    NEW = "NEW", "Новая"
    IN_PROGRESS = "IN_PROGRESS", "В работе"
    REVIEW = "REVIEW", "На проверке"
    BLOCKED = "BLOCKED", "Заблокирована"
    COMPLETED = "COMPLETED", "Выполнена"
    CANCELLED = "CANCELLED", "Отменена"


class TaskPriority(models.TextChoices):
    LOW = "LOW", "Низкий"
    NORMAL = "NORMAL", "Обычный"
    HIGH = "HIGH", "Высокий"
    URGENT = "URGENT", "Срочный"


class TaskQuerySet(models.QuerySet["Task"]):
    def overdue(self) -> "TaskQuerySet":
        return self.filter(due_at__lt=timezone.now()).exclude(
            status__in=Task.TERMINAL_STATUSES,
        )


class Task(models.Model):
    TERMINAL_STATUSES = (TaskStatus.COMPLETED, TaskStatus.CANCELLED)

    title = models.CharField("название", max_length=255)
    description = models.TextField("подробное описание", blank=True)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="постановщик",
        related_name="created_tasks",
        on_delete=models.PROTECT,
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="исполнитель",
        related_name="assigned_tasks",
        on_delete=models.PROTECT,
    )
    status = models.CharField(
        "статус",
        max_length=20,
        choices=TaskStatus.choices,
        default=TaskStatus.NEW,
    )
    priority = models.CharField(
        "приоритет",
        max_length=10,
        choices=TaskPriority.choices,
        default=TaskPriority.NORMAL,
    )
    created_at = models.DateTimeField("дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("дата обновления", auto_now=True)
    due_at = models.DateTimeField("срок выполнения", blank=True, null=True)
    completed_at = models.DateTimeField("дата выполнения", blank=True, null=True)
    archived = models.BooleanField("архивная", default=False)

    objects = TaskQuerySet.as_manager()

    class Meta:
        verbose_name = "задача"
        verbose_name_plural = "задачи"
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=("status",), name="tasks_task_status_idx"),
            models.Index(fields=("assignee",), name="tasks_task_assignee_idx"),
            models.Index(fields=("due_at",), name="tasks_task_due_at_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(archived=True) | ~Q(status=TaskStatus.COMPLETED),
                name="completed_tasks_are_archived",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    def get_absolute_url(self) -> str:
        return reverse("tasks:detail", kwargs={"pk": self.pk})

    def clean(self) -> None:
        super().clean()
        created_reference = self.created_at or timezone.now()
        if self.due_at and self.due_at < created_reference:
            raise ValidationError(
                {"due_at": "Срок выполнения не может быть раньше даты создания задачи."},
            )

    def save(self, *args: object, **kwargs: object) -> None:
        self.sync_completion_state()
        self.full_clean()
        super().save(*args, **kwargs)

    def set_status(self, status: str) -> None:
        self.status = status
        self.sync_completion_state()

    def unarchive(self) -> None:
        if self.status == TaskStatus.COMPLETED:
            self.set_status(TaskStatus.NEW)
        self.archived = False

    def sync_completion_state(self) -> None:
        if self.status == TaskStatus.COMPLETED and self.completed_at is None:
            self.completed_at = timezone.now()
        if self.status == TaskStatus.COMPLETED:
            self.archived = True
        elif self.status != TaskStatus.COMPLETED:
            self.completed_at = None

    def can_be_edited_by(self, user: object) -> bool:
        if not getattr(user, "is_authenticated", False):
            return False
        return bool(
            getattr(user, "is_superuser", False)
            or user == self.creator
            or user == self.assignee
        )

    def is_overdue_at(self, moment) -> bool:
        return bool(
            self.due_at
            and self.due_at < moment
            and self.status not in self.TERMINAL_STATUSES
        )

    @property
    def is_overdue(self) -> bool:
        return self.is_overdue_at(timezone.now())


class TaskAttachment(models.Model):
    task = models.ForeignKey(
        Task,
        verbose_name="задача",
        related_name="attachments",
        on_delete=models.CASCADE,
    )
    file = models.FileField("файл", upload_to=task_attachment_upload_to)
    original_name = models.CharField("имя файла", max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="загрузил",
        related_name="task_attachments",
        on_delete=models.PROTECT,
    )
    uploaded_at = models.DateTimeField("дата загрузки", auto_now_add=True)

    class Meta:
        verbose_name = "файл задачи"
        verbose_name_plural = "файлы задач"
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=("task",), name="task_attach_task_idx"),
            models.Index(fields=("uploaded_at",), name="task_attach_uploaded_idx"),
        ]

    def __str__(self) -> str:
        return self.original_name
