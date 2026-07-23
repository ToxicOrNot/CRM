from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone


def order_attachment_upload_to(instance: "OrderAttachment", filename: str) -> str:
    return f"orders/{instance.order_id}/attachments/{filename}"


IMAGE_ATTACHMENT_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".jpeg",
    ".jpg",
    ".png",
    ".webp",
}
HEIC_ATTACHMENT_EXTENSIONS = {".heic", ".heif"}


class OrderStatus(models.TextChoices):
    ACCEPTED = "ACCEPTED", "Новый"
    WAITING_RESPONSE = "WAITING_RESPONSE", "Ожидаем ответ/предоплату"
    IN_PROGRESS = "IN_PROGRESS", "В работе"
    READY = "READY", "Позвонили о готовности"
    DELIVERED = "DELIVERED", "Заказ отдан"
    CANCELLED = "CANCELLED", "Отменен"


class OrderQuerySet(models.QuerySet["Order"]):
    def active(self) -> "OrderQuerySet":
        return self.filter(archived=False)

    def archived(self) -> "OrderQuerySet":
        return self.filter(archived=True)

    def overdue(self) -> "OrderQuerySet":
        return self.filter(delivery_date__lt=timezone.localdate()).exclude(
            status__in=Order.TERMINAL_STATUSES,
        )


class Order(models.Model):
    TERMINAL_STATUSES = (OrderStatus.DELIVERED, OrderStatus.CANCELLED)

    order_date = models.DateField("Дата заказа", default=timezone.localdate)
    delivery_date = models.DateField("Дата выдачи", blank=True, null=True)
    status = models.CharField(
        "Статус",
        max_length=20,
        choices=OrderStatus.choices,
        default=OrderStatus.ACCEPTED,
    )
    client = models.ForeignKey(
        "clients.Client",
        verbose_name="Клиент",
        related_name="orders",
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
    )
    order_number = models.CharField("Номер заказа", max_length=100, blank=True)
    work_information = models.TextField("Информация о работе")
    contacts = models.TextField("Контакты")
    original_contacts = models.TextField("Исходная запись контактов", blank=True, default="")
    total_amount = models.DecimalField(
        "Сумма к оплате",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    advance_amount = models.DecimalField(
        "Аванс",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    additional_payment = models.DecimalField(
        "Доплата",
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    comment = models.TextField("Комментарий", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="Создал",
        related_name="created_orders",
        on_delete=models.PROTECT,
    )
    created_at = models.DateTimeField("Дата создания", auto_now_add=True)
    updated_at = models.DateTimeField("Дата изменения", auto_now=True)
    archived = models.BooleanField("Архивный", default=False)

    objects = OrderQuerySet.as_manager()

    class Meta:
        verbose_name = "заказ"
        verbose_name_plural = "заказы"
        ordering = ("-order_date", "-created_at")
        indexes = [
            models.Index(fields=("order_date",), name="orders_order_date_idx"),
            models.Index(fields=("delivery_date",), name="orders_delivery_date_idx"),
            models.Index(fields=("status",), name="orders_status_idx"),
            models.Index(fields=("archived",), name="orders_archived_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(total_amount__gte=Decimal("0.00")),
                name="order_total_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(advance_amount__gte=Decimal("0.00")),
                name="order_advance_amount_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(additional_payment__gte=Decimal("0.00")),
                name="order_additional_payment_non_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"Заказ {self.display_number}"

    def get_absolute_url(self) -> str:
        return reverse("orders:detail", kwargs={"pk": self.pk})

    @property
    def sequence_number(self) -> str:
        return str(self.pk) if self.pk else ""

    @property
    def display_number(self) -> str:
        return self.order_number or self.sequence_number

    @property
    def balance(self) -> Decimal:
        return self.total_amount - self.advance_amount - self.additional_payment

    @property
    def is_paid(self) -> bool:
        if self.total_amount != Decimal("0.00"):
            return self.balance == Decimal("0.00")
        else: return False

    @property
    def is_overdue(self) -> bool:
        return bool(
            self.delivery_date
            and self.delivery_date < timezone.localdate()
            and self.status not in self.TERMINAL_STATUSES
        )

    @property
    def can_be_archived(self) -> bool:
        return not self.archived

    def normalize_order_number(self) -> None:
        self.order_number = (self.order_number or "").strip()

    def sync_delivery_date(self) -> None:
        if self.status == OrderStatus.DELIVERED and self.delivery_date is None:
            self.delivery_date = timezone.localdate()
        elif self.status != OrderStatus.DELIVERED:
            self.delivery_date = None

    def clean(self) -> None:
        super().clean()
        self.normalize_order_number()
        self.sync_delivery_date()
        errors: dict[str, str] = {}

        if self.delivery_date and self.delivery_date < self.order_date:
            errors["delivery_date"] = "Дата выдачи не может быть раньше даты заказа."

        for field_name in ("total_amount", "advance_amount", "additional_payment"):
            value = getattr(self, field_name)
            if value < Decimal("0.00"):
                errors[field_name] = "Значение не может быть меньше нуля."

        if self.advance_amount + self.additional_payment > self.total_amount:
            errors["additional_payment"] = (
                "Сумма аванса и доплаты не должна превышать сумму заказа."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args: object, **kwargs: object) -> None:
        self.normalize_order_number()
        self.sync_delivery_date()
        self.full_clean()
        super().save(*args, **kwargs)

    def archive(self) -> None:
        self.archived = True

    def restore_from_archive(self) -> None:
        self.archived = False


class OrderAttachment(models.Model):
    order = models.ForeignKey(
        Order,
        verbose_name="заказ",
        related_name="attachments",
        on_delete=models.CASCADE,
    )
    file = models.FileField("файл", upload_to=order_attachment_upload_to)
    original_name = models.CharField("имя файла", max_length=255)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="загрузил",
        related_name="order_attachments",
        on_delete=models.PROTECT,
    )
    uploaded_at = models.DateTimeField("дата загрузки", auto_now_add=True)

    class Meta:
        verbose_name = "файл заказа"
        verbose_name_plural = "файлы заказов"
        ordering = ("-uploaded_at",)
        indexes = [
            models.Index(fields=("order",), name="order_attach_order_idx"),
            models.Index(fields=("uploaded_at",), name="order_attach_uploaded_idx"),
        ]

    def __str__(self) -> str:
        return self.original_name

    @property
    def is_image(self) -> bool:
        file_name = self.original_name or self.file.name
        return Path(file_name).suffix.lower() in IMAGE_ATTACHMENT_EXTENSIONS

    @property
    def is_heic_image(self) -> bool:
        file_name = self.original_name or self.file.name
        return Path(file_name).suffix.lower() in HEIC_ATTACHMENT_EXTENSIONS

    @property
    def preview_url(self) -> str:
        if self.is_heic_image:
            return reverse("orders:attachment_preview", kwargs={"pk": self.pk})
        return self.file.url
