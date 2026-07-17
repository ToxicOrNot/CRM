from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    position = models.CharField("должность", max_length=150, blank=True)
    department = models.CharField("отдел", max_length=150, blank=True)

    class Meta:
        verbose_name = "пользователь"
        verbose_name_plural = "пользователи"
