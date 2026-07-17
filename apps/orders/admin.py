from django.contrib import admin

from apps.orders.models import Order


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "sequence_number_display",
        "order_date",
        "display_number_display",
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
    search_fields = ("order_number", "contacts", "work_information")
    readonly_fields = (
        "delivery_date",
        "created_by",
        "created_at",
        "updated_at",
        "balance_display",
    )
    date_hierarchy = "order_date"

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "order_date",
                    "delivery_date",
                    "status",
                    "order_number",
                    "work_information",
                    "contacts",
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
