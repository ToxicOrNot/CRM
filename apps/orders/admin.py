from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.orders.models import Order, OrderAttachment


class OrderAttachmentInline(admin.TabularInline):
    model = OrderAttachment
    extra = 0
    readonly_fields = ("original_name", "uploaded_by", "uploaded_at")
    fields = ("file", "original_name", "uploaded_by", "uploaded_at")


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    inlines = (OrderAttachmentInline,)
    actions = ("archive_selected_orders",)
    list_display = (
        "sequence_number_display",
        "order_date",
        "display_number_display",
        "client",
        "status",
        "short_contacts",
        "total_amount",
        "advance_amount",
        "additional_payment",
        "balance_display",
        "delivery_date",
        "archived",
    )
    list_filter = ("status", "order_date", "delivery_date", "archived")
    search_fields = ("order_number", "contacts", "original_contacts", "work_information", "client__display_name")
    readonly_fields = (
        "delivery_date",
        "original_contacts",
        "created_by",
        "created_at",
        "updated_at",
        "balance_display",
    )
    date_hierarchy = "order_date"

    @admin.action(description="Перенести выбранные заказы в архив")
    def archive_selected_orders(self, request: HttpRequest, queryset: QuerySet[Order]) -> None:
        updated_count = queryset.filter(archived=False).update(archived=True, updated_at=timezone.now())
        self.message_user(request, f"Заказов перенесено в архив: {updated_count}.")

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "order_date",
                    "delivery_date",
                    "status",
                    "client",
                    "order_number",
                    "work_information",
                    "contacts",
                    "original_contacts",
                    "comment",
                    "archived",
                ),
            },
        ),
        (
            "Финансы",
            {
                "fields": (
                    "total_amount",
                    "advance_amount",
                    "additional_payment",
                    "balance_display",
                ),
            },
        ),
        (
            "Служебное",
            {"fields": ("created_by", "created_at", "updated_at")},
        ),
    )

    def short_contacts(self, obj: Order) -> str:
        return obj.contacts[:80]

    short_contacts.short_description = "Контакты"

    def sequence_number_display(self, obj: Order) -> str:
        return obj.sequence_number

    sequence_number_display.short_description = "№"
    sequence_number_display.admin_order_field = "id"

    def display_number_display(self, obj: Order) -> str:
        return obj.display_number

    display_number_display.short_description = "Номер заказа"
    display_number_display.admin_order_field = "order_number"

    def balance_display(self, obj: Order) -> str:
        return f"{obj.balance:.2f}"

    balance_display.short_description = "Остаток"

    def save_model(self, request, obj: Order, form, change: bool) -> None:
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change: bool) -> None:
        instances = formset.save(commit=False)
        for deleted_object in formset.deleted_objects:
            deleted_object.delete()
        for instance in instances:
            if isinstance(instance, OrderAttachment) and instance.file:
                if not instance.original_name:
                    instance.original_name = instance.file.name
                if not instance.uploaded_by_id:
                    instance.uploaded_by = request.user
            instance.save()
        formset.save_m2m()


@admin.register(OrderAttachment)
class OrderAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "order", "uploaded_by", "uploaded_at")
    list_filter = ("uploaded_at", "uploaded_by")
    search_fields = ("original_name", "order__order_number", "order__work_information")
    readonly_fields = ("original_name", "uploaded_by", "uploaded_at")

    def save_model(self, request, obj: OrderAttachment, form, change: bool) -> None:
        if obj.file and not obj.original_name:
            obj.original_name = obj.file.name
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
