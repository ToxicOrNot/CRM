from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UserSelectLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        User = get_user_model()
        cls.user = User.objects.create_user(
            username="worker",
            first_name="Марина",
            last_name="Иванова",
            password="unused",
        )

    def test_login_page_uses_user_select_without_password(self) -> None:
        response = self.client.get(reverse("login"))

        self.assertContains(response, 'name="user"')
        self.assertContains(response, "Марина Иванова")
        self.assertNotContains(response, 'name="password"')

    def test_user_can_login_by_selecting_account(self) -> None:
        response = self.client.post(
            reverse("login"),
            data={"user": self.user.pk, "next": reverse("tasks:list")},
        )

        self.assertRedirects(response, reverse("tasks:list"))
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
