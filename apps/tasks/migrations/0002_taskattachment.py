# Generated for task attachments.

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import apps.tasks.models


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("tasks", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskAttachment",
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
                (
                    "file",
                    models.FileField(
                        upload_to=apps.tasks.models.task_attachment_upload_to,
                        verbose_name="файл",
                    ),
                ),
                (
                    "original_name",
                    models.CharField(max_length=255, verbose_name="имя файла"),
                ),
                (
                    "uploaded_at",
                    models.DateTimeField(
                        auto_now_add=True,
                        verbose_name="дата загрузки",
                    ),
                ),
                (
                    "task",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="attachments",
                        to="tasks.task",
                        verbose_name="задача",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="task_attachments",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="загрузил",
                    ),
                ),
            ],
            options={
                "verbose_name": "файл задачи",
                "verbose_name_plural": "файлы задач",
                "ordering": ("-uploaded_at",),
            },
        ),
        migrations.AddIndex(
            model_name="taskattachment",
            index=models.Index(fields=["task"], name="task_attach_task_idx"),
        ),
        migrations.AddIndex(
            model_name="taskattachment",
            index=models.Index(fields=["uploaded_at"], name="task_attach_uploaded_idx"),
        ),
    ]
