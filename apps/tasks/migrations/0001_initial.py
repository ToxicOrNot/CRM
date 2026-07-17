# Generated for the initial CRM project setup.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Task",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(max_length=255, verbose_name="название")),
                (
                    "description",
                    models.TextField(blank=True, verbose_name="подробное описание"),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("NEW", "Новая"),
                            ("IN_PROGRESS", "В работе"),
                            ("REVIEW", "На проверке"),
                            ("BLOCKED", "Заблокирована"),
                            ("COMPLETED", "Выполнена"),
                            ("CANCELLED", "Отменена"),
                        ],
                        default="NEW",
                        max_length=20,
                        verbose_name="статус",
                    ),
                ),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("LOW", "Низкий"),
                            ("NORMAL", "Обычный"),
                            ("HIGH", "Высокий"),
                            ("URGENT", "Срочный"),
                        ],
                        default="NORMAL",
                        max_length=10,
                        verbose_name="приоритет",
                    ),
                ),
                (
                    "created_at",
                    models.DateTimeField(auto_now_add=True, verbose_name="дата создания"),
                ),
                (
                    "updated_at",
                    models.DateTimeField(auto_now=True, verbose_name="дата обновления"),
                ),
                (
                    "due_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="срок выполнения",
                    ),
                ),
                (
                    "completed_at",
                    models.DateTimeField(
                        blank=True,
                        null=True,
                        verbose_name="дата выполнения",
                    ),
                ),
                ("archived", models.BooleanField(default=False, verbose_name="архивная")),
                (
                    "assignee",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assigned_tasks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="исполнитель",
                    ),
                ),
                (
                    "creator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_tasks",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="постановщик",
                    ),
                ),
            ],
            options={
                "verbose_name": "задача",
                "verbose_name_plural": "задачи",
                "ordering": ("-created_at",),
            },
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["status"], name="tasks_task_status_idx"),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["assignee"], name="tasks_task_assignee_idx"),
        ),
        migrations.AddIndex(
            model_name="task",
            index=models.Index(fields=["due_at"], name="tasks_task_due_at_idx"),
        ),
    ]
