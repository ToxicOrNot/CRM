from django.db import migrations, models


def archive_completed_tasks(apps, schema_editor) -> None:
    Task = apps.get_model("tasks", "Task")
    Task.objects.filter(status="COMPLETED", archived=False).update(archived=True)


def unarchive_completed_tasks(apps, schema_editor) -> None:
    Task = apps.get_model("tasks", "Task")
    Task.objects.filter(status="COMPLETED", archived=True).update(archived=False)


class Migration(migrations.Migration):
    dependencies = [
        ("tasks", "0002_taskattachment"),
    ]

    operations = [
        migrations.RunPython(archive_completed_tasks, unarchive_completed_tasks),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=models.Q(archived=True) | ~models.Q(status="COMPLETED"),
                name="completed_tasks_are_archived",
            ),
        ),
    ]
