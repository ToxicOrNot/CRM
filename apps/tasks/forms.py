from datetime import datetime, time

from django import forms
from django.utils import timezone

from apps.tasks.models import Task


class TaskForm(forms.ModelForm):
    due_at = forms.DateField(
        label="Срок выполнения",
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(
            attrs={"type": "date"},
            format="%Y-%m-%d",
        ),
    )

    class Meta:
        model = Task
        fields = (
            "title",
            "description",
            "assignee",
            "priority",
            "due_at",
            "archived",
        )
        labels = {
            "title": "Название",
            "description": "Описание",
            "assignee": "Исполнитель",
            "priority": "Приоритет",
            "archived": "Архивная задача",
        }
        widgets = {
            "description": forms.Textarea(attrs={"rows": 5}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.due_at:
            self.initial["due_at"] = timezone.localtime(self.instance.due_at).date()
        for name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, forms.Select):
                widget.attrs.setdefault("class", "form-select")
            else:
                widget.attrs.setdefault("class", "form-control")
            if name == "assignee":
                field.queryset = field.queryset.order_by("last_name", "first_name", "username")

    def clean_due_at(self):
        due_date = self.cleaned_data["due_at"]
        if due_date is None:
            return None
        due_datetime = datetime.combine(due_date, time.max)
        return timezone.make_aware(due_datetime, timezone.get_current_timezone())
