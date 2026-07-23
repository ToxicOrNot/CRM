from django.contrib import admin

from apps.tasks.models import Task, TaskAttachment


class TaskAttachmentInline(admin.TabularInline):
    model = TaskAttachment
    extra = 0
    readonly_fields = ("original_name", "uploaded_by", "uploaded_at")
    fields = ("file", "original_name", "uploaded_by", "uploaded_at")


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    inlines = (TaskAttachmentInline,)
    list_display = (
        "title",
        "assignee",
        "order",
        "status",
        "priority",
        "due_at",
        "creator",
        "last_modified_by",
        "created_at",
        "archived",
    )
    list_filter = ("status", "priority", "assignee", "archived")
    search_fields = ("title", "description", "order__order_number", "order__contacts")
    readonly_fields = ("creator", "last_modified_by", "created_at", "updated_at", "completed_at")
    autocomplete_fields = ("assignee", "order")
    date_hierarchy = "created_at"

    fieldsets = (
        (
            "Основное",
            {
                "fields": (
                    "title",
                    "description",
                    "creator",
                    "last_modified_by",
                    "assignee",
                    "order",
                    "status",
                    "priority",
                    "due_at",
                    "completed_at",
                    "archived",
                ),
            },
        ),
        (
            "Служебные даты",
            {"fields": ("created_at", "updated_at")},
        ),
    )

    def save_model(self, request, obj: Task, form, change: bool) -> None:
        if not obj.pk:
            obj.creator = request.user
        elif change:
            obj.last_modified_by = request.user
        super().save_model(request, obj, form, change)

    def save_formset(self, request, form, formset, change: bool) -> None:
        instances = formset.save(commit=False)
        for deleted_object in formset.deleted_objects:
            deleted_object.delete()
        for instance in instances:
            if isinstance(instance, TaskAttachment) and instance.file:
                if not instance.original_name:
                    instance.original_name = instance.file.name
                if not instance.uploaded_by_id:
                    instance.uploaded_by = request.user
            instance.save()
        formset.save_m2m()


@admin.register(TaskAttachment)
class TaskAttachmentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "task", "uploaded_by", "uploaded_at")
    list_filter = ("uploaded_at", "uploaded_by")
    search_fields = ("original_name", "task__title")
    readonly_fields = ("original_name", "uploaded_by", "uploaded_at")

    def save_model(self, request, obj: TaskAttachment, form, change: bool) -> None:
        if obj.file and not obj.original_name:
            obj.original_name = obj.file.name
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)
