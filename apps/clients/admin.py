from django.contrib import admin

from apps.clients.models import Client, ClientContact


class ClientContactInline(admin.TabularInline):
    model = ClientContact
    extra = 1
    fields = ("contact_type", "raw_value", "normalized_value", "label", "comment", "is_primary")
    readonly_fields = ("normalized_value",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = (
        "display_name",
        "preferred_channel",
        "primary_contact_display",
        "contacts_count",
        "orders_count",
        "created_at",
        "archived",
    )
    list_filter = ("preferred_channel", "archived")
    search_fields = (
        "display_name",
        "source_text",
        "comment",
        "contacts__raw_value",
        "contacts__normalized_value",
    )
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = (ClientContactInline,)

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "display_name",
                    "preferred_channel",
                    "comment",
                    "source_text",
                    "archived",
                ),
            },
        ),
        (
            "Служебное",
            {"fields": ("created_by", "created_at", "updated_at")},
        ),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.prefetch_related("contacts", "orders")

    def contacts_count(self, obj: Client) -> int:
        return obj.contacts.count()

    contacts_count.short_description = "Контактов"

    def orders_count(self, obj: Client) -> int:
        return obj.orders.count()

    orders_count.short_description = "Заказов"

    def save_model(self, request, obj: Client, form, change: bool) -> None:
        if not obj.pk:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ClientContact)
class ClientContactAdmin(admin.ModelAdmin):
    list_display = ("client", "contact_type", "raw_value", "normalized_value", "is_primary")
    list_filter = ("contact_type", "is_primary")
    search_fields = ("client__display_name", "raw_value", "normalized_value")
    readonly_fields = ("normalized_value", "created_at", "updated_at")

