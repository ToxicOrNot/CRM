from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse


class ContactType(models.TextChoices):
    PHONE = "PHONE", "Телефон"
    WHATSAPP = "WHATSAPP", "WhatsApp"
    TELEGRAM = "TELEGRAM", "Telegram"
    MAX = "MAX", "MAX"
    EMAIL = "EMAIL", "Email"
    OTHER = "OTHER", "Другое"


class ClientQuerySet(models.QuerySet["Client"]):
    def active(self) -> "ClientQuerySet":
        return self.filter(archived=False)

    def archived(self) -> "ClientQuerySet":
        return self.filter(archived=True)


class Client(models.Model):
    display_name = models.CharField("Имя клиента", max_length=255, blank=True)
    preferred_channel = models.CharField(
        "Предпочтительный канал связи",
        max_length=20,
        choices=ContactType.choices,
        blank=True,
    )
    comment = models.TextField("Комментарий", blank=True)
    source_text = models.TextField("Исходная запись", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Кто создал",
        related_name="created_clients",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)
    archived = models.BooleanField("В архиве", default=False)

    objects = ClientQuerySet.as_manager()

    class Meta:
        verbose_name = "клиент"
        verbose_name_plural = "клиенты"
        ordering = ("display_name", "-created_at")
        indexes = [
            models.Index(fields=("display_name",), name="clients_name_idx"),
            models.Index(fields=("preferred_channel",), name="clients_channel_idx"),
            models.Index(fields=("archived",), name="clients_archived_idx"),
        ]

    def __str__(self) -> str:
        return self.display_name or self.primary_contact_display or f"Клиент {self.pk}"

    def get_absolute_url(self) -> str:
        return reverse("clients:detail", kwargs={"pk": self.pk})

    @property
    def primary_contact(self) -> "ClientContact | None":
        contacts = list(getattr(self, "_prefetched_objects_cache", {}).get("contacts", []))
        if contacts:
            return next((contact for contact in contacts if contact.is_primary), contacts[0])
        if not self.pk:
            return None
        return self.contacts.order_by("-is_primary", "pk").first()

    @property
    def primary_contact_display(self) -> str:
        contact = self.primary_contact
        return contact.display_value if contact else ""

    @property
    def available_channels_display(self) -> str:
        contact_types = []
        for contact in self.contacts.all():
            label = contact.get_contact_type_display()
            if label not in contact_types:
                contact_types.append(label)
        return ", ".join(contact_types)

    def normalize_display_name(self) -> None:
        self.display_name = " ".join((self.display_name or "").strip().split())

    def clean(self) -> None:
        super().clean()
        self.normalize_display_name()

    def save(self, *args: object, **kwargs: object) -> None:
        self.normalize_display_name()
        super().save(*args, **kwargs)

    def archive(self) -> None:
        self.archived = True

    def restore_from_archive(self) -> None:
        self.archived = False


class ClientContact(models.Model):
    client = models.ForeignKey(
        Client,
        verbose_name="Клиент",
        related_name="contacts",
        on_delete=models.CASCADE,
    )
    contact_type = models.CharField("Тип", max_length=20, choices=ContactType.choices)
    raw_value = models.CharField("Значение", max_length=255)
    normalized_value = models.CharField("Нормализованное значение", max_length=255, blank=True)
    label = models.CharField("Подпись", max_length=255, blank=True)
    comment = models.TextField("Комментарий", blank=True)
    is_primary = models.BooleanField("Основной контакт", default=False)
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)

    class Meta:
        verbose_name = "контакт клиента"
        verbose_name_plural = "контакты клиентов"
        ordering = ("-is_primary", "pk")
        indexes = [
            models.Index(fields=("contact_type",), name="client_contact_type_idx"),
            models.Index(fields=("normalized_value",), name="client_contact_norm_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["client"],
                condition=Q(is_primary=True),
                name="unique_primary_contact_per_client",
            ),
            models.UniqueConstraint(
                fields=["client", "contact_type", "normalized_value"],
                condition=~Q(normalized_value=""),
                name="unique_contact_value_per_client",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_contact_type_display()}: {self.display_value}"

    @property
    def display_value(self) -> str:
        from apps.clients.services.contact_normalizer import format_contact_value

        return format_contact_value(self.contact_type, self.normalized_value, self.raw_value)

    @property
    def is_phone_based(self) -> bool:
        return self.normalized_value.startswith("+") and self.contact_type in {
            ContactType.PHONE,
            ContactType.WHATSAPP,
            ContactType.TELEGRAM,
            ContactType.MAX,
        }

    def clean(self) -> None:
        super().clean()
        from apps.clients.services.contact_normalizer import normalize_contact_value

        self.raw_value = (self.raw_value or "").strip()
        self.label = " ".join((self.label or "").strip().split())
        if not self.raw_value:
            raise ValidationError({"raw_value": "Укажите значение контакта."})
        self.normalized_value = normalize_contact_value(self.contact_type, self.raw_value)

    def save(self, *args: object, **kwargs: object) -> None:
        self.full_clean()
        super().save(*args, **kwargs)
