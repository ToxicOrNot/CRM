from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.tasks.models import Task, TaskPriority, TaskStatus


class DashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        User = get_user_model()
        cls.user = User.objects.create_user(username="user")
        cls.other_user = User.objects.create_user(username="other")

    def create_task(self, title: str, **kwargs: object) -> Task:
        data = {
            "title": title,
            "creator": self.user,
            "assignee": self.user,
            "priority": TaskPriority.NORMAL,
            "status": TaskStatus.NEW,
            "due_at": timezone.now() + timedelta(days=5),
        }
        data.update(kwargs)
        return Task.objects.create(**data)

    def test_dashboard_shows_top_three_current_user_tasks(self) -> None:
        now = timezone.now()
        due_today_low = self.create_task(
            "Сегодня низкий",
            priority=TaskPriority.LOW,
            due_at=now + timedelta(hours=3),
        )
        due_today_urgent = self.create_task(
            "Сегодня срочный",
            description="Описание срочной задачи",
            priority=TaskPriority.URGENT,
            due_at=now + timedelta(hours=3),
        )
        due_tomorrow_high = self.create_task(
            "Завтра высокий",
            priority=TaskPriority.HIGH,
            due_at=now + timedelta(days=1),
        )
        self.create_task(
            "Позже срочный",
            priority=TaskPriority.URGENT,
            due_at=now + timedelta(days=7),
        )
        self.create_task(
            "Чужая задача",
            assignee=self.other_user,
            priority=TaskPriority.URGENT,
            due_at=now + timedelta(hours=1),
        )
        self.create_task(
            "Архивная задача",
            archived=True,
            priority=TaskPriority.URGENT,
            due_at=now + timedelta(hours=1),
        )
        self.create_task(
            "Выполненная задача",
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.URGENT,
            due_at=now + timedelta(hours=1),
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(
            list(response.context["priority_tasks"]),
            [due_today_urgent, due_today_low, due_tomorrow_high],
        )
        self.assertContains(response, "Сегодня срочный")
        self.assertContains(response, "Описание срочной задачи")
        self.assertNotContains(response, "Позже срочный")
        self.assertNotContains(response, "Чужая задача")
        self.assertNotContains(response, "Архивная задача")
