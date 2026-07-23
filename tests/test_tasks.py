from io import BytesIO
from datetime import timedelta
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.orders.models import Order
from apps.tasks.forms import TaskForm
from apps.tasks.models import Task, TaskAttachment, TaskPriority, TaskStatus


class TaskWorkflowTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_media = TemporaryDirectory()
        cls.media_override = override_settings(MEDIA_ROOT=cls.temp_media.name)
        cls.media_override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls) -> None:
        super().tearDownClass()
        cls.media_override.disable()
        cls.temp_media.cleanup()

    @classmethod
    def setUpTestData(cls) -> None:
        User = get_user_model()
        cls.creator = User.objects.create_user(
            username="creator",
            password="password",
            first_name="Иван",
        )
        cls.assignee = User.objects.create_user(
            username="assignee",
            password="password",
            first_name="Анна",
        )
        cls.outsider = User.objects.create_user(
            username="outsider",
            password="password",
        )

    def create_task(self, **kwargs: object) -> Task:
        data = {
            "title": "Тестовая задача",
            "description": "",
            "creator": self.creator,
            "assignee": self.assignee,
            "status": TaskStatus.NEW,
            "priority": TaskPriority.NORMAL,
        }
        data.update(kwargs)
        return Task.objects.create(**data)

    def form_data(self, task: Task | None = None, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "title": task.title if task else "Новая задача",
            "description": task.description if task else "",
            "assignee": task.assignee_id if task else self.assignee.pk,
            "priority": task.priority if task else TaskPriority.NORMAL,
            "due_at": "",
        }
        data.update(overrides)
        return data

    def test_anonymous_user_is_redirected_to_login(self) -> None:
        response = self.client.get(reverse("tasks:list"))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response["Location"])

    def test_authenticated_user_can_create_task(self) -> None:
        self.client.force_login(self.creator)

        response = self.client.post(reverse("tasks:create"), data=self.form_data())

        self.assertRedirects(response, reverse("tasks:list"))
        self.assertTrue(Task.objects.filter(title="Новая задача").exists())

    def test_creator_is_set_to_current_user_on_create(self) -> None:
        self.client.force_login(self.creator)

        self.client.post(reverse("tasks:create"), data=self.form_data(title="Авторская задача"))

        task = Task.objects.get(title="Авторская задача")
        self.assertEqual(task.creator, self.creator)

    def test_user_sees_assigned_tasks_on_my_tasks_page(self) -> None:
        assigned_task = self.create_task(title="Назначено мне")
        self.create_task(title="Назначено другому", assignee=self.outsider)
        self.client.force_login(self.assignee)

        response = self.client.get(reverse("tasks:my"))

        self.assertContains(response, assigned_task.title)
        self.assertNotContains(response, "Назначено другому")

    def test_authenticated_user_can_edit_foreign_task(self) -> None:
        task = self.create_task(title="Чужая задача")
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("tasks:edit", kwargs={"pk": task.pk}),
            data=self.form_data(task, title="Изменено другим пользователем"),
        )

        self.assertRedirects(response, task.get_absolute_url())
        task.refresh_from_db()
        self.assertEqual(task.title, "Изменено другим пользователем")
        self.assertEqual(task.last_modified_by, self.outsider)

    def test_creator_can_edit_task(self) -> None:
        task = self.create_task(title="Исходное название")
        self.client.force_login(self.creator)

        response = self.client.post(
            reverse("tasks:edit", kwargs={"pk": task.pk}),
            data=self.form_data(task, title="Обновлено постановщиком"),
        )

        self.assertRedirects(response, task.get_absolute_url())
        task.refresh_from_db()
        self.assertEqual(task.title, "Обновлено постановщиком")
        self.assertEqual(task.last_modified_by, self.creator)

    def test_assignee_can_edit_task(self) -> None:
        task = self.create_task(title="Исходное название")
        self.client.force_login(self.assignee)

        response = self.client.post(
            reverse("tasks:edit", kwargs={"pk": task.pk}),
            data=self.form_data(task, title="Обновлено исполнителем"),
        )

        self.assertRedirects(response, task.get_absolute_url())
        task.refresh_from_db()
        self.assertEqual(task.title, "Обновлено исполнителем")
        self.assertEqual(task.last_modified_by, self.assignee)

    def test_status_field_is_not_rendered_in_task_form(self) -> None:
        self.client.force_login(self.creator)

        response = self.client.get(reverse("tasks:create"))

        self.assertNotContains(response, 'name="status"')

    def test_task_form_has_drag_and_drop_file_upload(self) -> None:
        self.client.force_login(self.creator)

        response = self.client.get(reverse("tasks:create"))

        self.assertContains(response, "data-file-dropzone")
        self.assertContains(response, "data-file-list")
        self.assertContains(response, "js/file_dropzone.js")

    def test_task_form_order_field_uses_work_information_as_label(self) -> None:
        order = Order.objects.create(
            order_number="A-100",
            work_information="10 фото 10x15 + 1 фото 15x20 матовые",
            contacts="Клиент",
            created_by=self.creator,
        )

        form = TaskForm()
        label = form.fields["order"].label_from_instance(order)

        self.assertEqual(label, "10 фото 10x15 + 1 фото 15x20 матовые")
        self.assertNotIn("A-100", label)

    def test_completed_status_sets_completed_at(self) -> None:
        task = self.create_task()

        task.set_status(TaskStatus.COMPLETED)
        task.save()

        task.refresh_from_db()
        self.assertIsNotNone(task.completed_at)
        self.assertTrue(task.archived)

    def test_leaving_completed_status_clears_completed_at(self) -> None:
        task = self.create_task()
        task.set_status(TaskStatus.COMPLETED)
        task.save()

        task.set_status(TaskStatus.IN_PROGRESS)
        task.save()

        task.refresh_from_db()
        self.assertIsNone(task.completed_at)

    def test_creator_can_mark_task_completed_from_quick_action(self) -> None:
        task = self.create_task(status=TaskStatus.IN_PROGRESS)
        self.client.force_login(self.creator)

        response = self.client.post(
            reverse("tasks:complete", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:list")},
        )

        self.assertRedirects(response, reverse("tasks:list"))
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)
        self.assertTrue(task.archived)
        self.assertEqual(task.last_modified_by, self.creator)
        self.assertEqual(self.client.session["task_completion_undo"]["task_id"], task.pk)

    def test_completion_notice_is_visible_after_quick_action(self) -> None:
        task = self.create_task(title="Важная задача", status=TaskStatus.IN_PROGRESS)
        self.client.force_login(self.creator)

        self.client.post(
            reverse("tasks:complete", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:list")},
        )
        response = self.client.get(reverse("tasks:list"))

        self.assertContains(response, "Задача «Важная задача» отмечена выполненной.")
        self.assertContains(response, "Отменить")

    def test_completion_notice_is_rendered_only_once(self) -> None:
        task = self.create_task(title="Одноразовое уведомление", status=TaskStatus.IN_PROGRESS)
        self.client.force_login(self.creator)

        self.client.post(
            reverse("tasks:complete", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:list")},
        )
        first_response = self.client.get(reverse("tasks:list"))
        second_response = self.client.get(reverse("tasks:archive"))

        self.assertContains(first_response, "Задача «Одноразовое уведомление» отмечена выполненной.")
        self.assertNotContains(second_response, "Задача «Одноразовое уведомление» отмечена выполненной.")

    def test_creator_can_undo_completed_quick_action(self) -> None:
        task = self.create_task(status=TaskStatus.IN_PROGRESS)
        self.client.force_login(self.creator)
        self.client.post(
            reverse("tasks:complete", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:list")},
        )

        response = self.client.post(
            reverse("tasks:undo_complete", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:list")},
        )

        self.assertRedirects(response, reverse("tasks:list"))
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertIsNone(task.completed_at)
        self.assertFalse(task.archived)
        self.assertEqual(task.last_modified_by, self.creator)
        self.assertNotIn("task_completion_undo", self.client.session)

    def test_authenticated_user_can_mark_foreign_task_completed(self) -> None:
        task = self.create_task(status=TaskStatus.IN_PROGRESS)
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("tasks:complete", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:list")},
        )

        self.assertRedirects(response, reverse("tasks:list"))
        task.refresh_from_db()
        self.assertEqual(task.status, TaskStatus.COMPLETED)
        self.assertTrue(task.archived)
        self.assertEqual(task.last_modified_by, self.outsider)

    def test_archive_page_shows_archived_tasks_only(self) -> None:
        archived_task = self.create_task(title="Архивная задача", archived=True)
        active_task = self.create_task(title="Рабочая задача", archived=False)
        self.client.force_login(self.creator)

        archive_response = self.client.get(reverse("tasks:archive"))
        active_response = self.client.get(reverse("tasks:list"))

        self.assertContains(archive_response, archived_task.title)
        self.assertNotContains(archive_response, active_task.title)
        self.assertContains(active_response, active_task.title)
        self.assertNotContains(active_response, archived_task.title)
        self.assertContains(archive_response, "Убрать из архива")

    def test_creator_can_unarchive_task(self) -> None:
        task = self.create_task(
            title="Вернуть из архива",
            archived=True,
            status=TaskStatus.IN_PROGRESS,
        )
        self.client.force_login(self.creator)

        response = self.client.post(
            reverse("tasks:unarchive", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:archive")},
        )

        self.assertRedirects(response, reverse("tasks:archive"))
        task.refresh_from_db()
        self.assertFalse(task.archived)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(task.last_modified_by, self.creator)

    def test_unarchiving_completed_task_moves_it_to_new(self) -> None:
        task = self.create_task(title="Выполненная архивная")
        task.set_status(TaskStatus.COMPLETED)
        task.save()
        self.client.force_login(self.creator)

        response = self.client.post(reverse("tasks:unarchive", kwargs={"pk": task.pk}))

        self.assertRedirects(response, reverse("tasks:archive"))
        task.refresh_from_db()
        self.assertFalse(task.archived)
        self.assertEqual(task.status, TaskStatus.NEW)
        self.assertIsNone(task.completed_at)
        self.assertEqual(task.last_modified_by, self.creator)

    def test_authenticated_user_can_unarchive_foreign_task(self) -> None:
        task = self.create_task(archived=True, status=TaskStatus.IN_PROGRESS)
        self.client.force_login(self.outsider)

        response = self.client.post(
            reverse("tasks:unarchive", kwargs={"pk": task.pk}),
            data={"next": reverse("tasks:archive")},
        )

        self.assertRedirects(response, reverse("tasks:archive"))
        task.refresh_from_db()
        self.assertFalse(task.archived)
        self.assertEqual(task.status, TaskStatus.IN_PROGRESS)
        self.assertEqual(task.last_modified_by, self.outsider)

    def test_task_detail_shows_last_modifier(self) -> None:
        task = self.create_task(last_modified_by=self.outsider)
        self.client.force_login(self.creator)

        response = self.client.get(reverse("tasks:detail", kwargs={"pk": task.pk}))

        self.assertContains(response, "Изменил")
        self.assertContains(response, self.outsider.username)

    def test_overdue_tasks_are_detected(self) -> None:
        task = self.create_task()
        Task.objects.filter(pk=task.pk).update(
            created_at=timezone.now() - timedelta(days=3),
            due_at=timezone.now() - timedelta(days=1),
        )
        task.refresh_from_db()

        completed_task = self.create_task(title="Выполненная")
        Task.objects.filter(pk=completed_task.pk).update(
            created_at=timezone.now() - timedelta(days=3),
            due_at=timezone.now() - timedelta(days=1),
            status=TaskStatus.COMPLETED,
            archived=True,
        )
        completed_task.refresh_from_db()

        self.assertTrue(task.is_overdue)
        self.assertFalse(completed_task.is_overdue)
        self.assertIn(task, Task.objects.overdue())
        self.assertNotIn(completed_task, Task.objects.overdue())

    def test_due_at_cannot_be_before_created_at(self) -> None:
        task = self.create_task()
        task.due_at = task.created_at - timedelta(seconds=1)

        with self.assertRaises(ValidationError):
            task.full_clean()

    def test_authenticated_user_can_attach_file_on_create(self) -> None:
        self.client.force_login(self.creator)
        uploaded_file = SimpleUploadedFile(
            "brief.txt",
            b"Task file content",
            content_type="text/plain",
        )

        response = self.client.post(
            reverse("tasks:create"),
            data={**self.form_data(title="Задача с файлом"), "attachments": uploaded_file},
        )

        self.assertRedirects(response, reverse("tasks:list"))
        task = Task.objects.get(title="Задача с файлом")
        attachment = TaskAttachment.objects.get(task=task)
        self.assertEqual(attachment.original_name, "brief.txt")
        self.assertEqual(attachment.uploaded_by, self.creator)
        self.assertTrue(attachment.file.name.startswith(f"tasks/{task.pk}/attachments/"))

    def test_attachment_link_is_visible_in_task_list(self) -> None:
        task = self.create_task(title="Задача с видимым файлом")
        TaskAttachment.objects.create(
            task=task,
            file=SimpleUploadedFile("document.txt", b"content"),
            original_name="document.txt",
            uploaded_by=self.creator,
        )
        self.client.force_login(self.assignee)

        response = self.client.get(reverse("tasks:my"))

        self.assertContains(response, "document.txt")
        self.assertContains(response, "/media/tasks/")

    def test_can_download_all_task_attachments_as_zip(self) -> None:
        task = self.create_task(title="Задача с архивом файлов")
        TaskAttachment.objects.create(
            task=task,
            file=SimpleUploadedFile("first.txt", b"first"),
            original_name="first.txt",
            uploaded_by=self.creator,
        )
        TaskAttachment.objects.create(
            task=task,
            file=SimpleUploadedFile("second.txt", b"second"),
            original_name="second.txt",
            uploaded_by=self.creator,
        )
        self.client.force_login(self.assignee)

        response = self.client.get(reverse("tasks:download_attachments", kwargs={"pk": task.pk}))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/zip")
        with ZipFile(BytesIO(response.content)) as zip_file:
            self.assertEqual(set(zip_file.namelist()), {"first.txt", "second.txt"})
            self.assertEqual(zip_file.read("first.txt"), b"first")

    def test_tasks_can_be_sorted_by_title(self) -> None:
        beta = self.create_task(title="Бета")
        alpha = self.create_task(title="Альфа")
        self.client.force_login(self.creator)

        response = self.client.get(reverse("tasks:list"), {"sort": "title", "direction": "asc"})

        self.assertEqual(list(response.context["tasks"]), [alpha, beta])

    def test_tasks_can_be_sorted_by_priority(self) -> None:
        low = self.create_task(title="Низкий", priority=TaskPriority.LOW)
        urgent = self.create_task(title="Срочный", priority=TaskPriority.URGENT)
        high = self.create_task(title="Высокий", priority=TaskPriority.HIGH)
        self.client.force_login(self.creator)

        response = self.client.get(
            reverse("tasks:list"),
            {"sort": "priority", "direction": "desc"},
        )

        self.assertEqual(list(response.context["tasks"]), [urgent, high, low])

    def test_tasks_can_be_sorted_by_due_date(self) -> None:
        later = self.create_task(title="Позже")
        earlier = self.create_task(title="Раньше")
        Task.objects.filter(pk=later.pk).update(due_at=timezone.now() + timedelta(days=3))
        Task.objects.filter(pk=earlier.pk).update(due_at=timezone.now() + timedelta(days=1))
        self.client.force_login(self.creator)

        response = self.client.get(reverse("tasks:list"), {"sort": "due_at", "direction": "asc"})

        self.assertEqual(list(response.context["tasks"]), [earlier, later])
