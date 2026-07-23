from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.clients.models import Client, ClientContact
from apps.clients.services.contact_normalizer import normalize_contact_value


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ("display_name", "preferred_channel", "comment", "source_text")
        labels = {
            "display_name": "Имя клиента",
            "preferred_channel": "Предпочтительный канал связи",
            "comment": "Комментарий",
            "source_text": "Исходная запись",
        }
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 3}),
            "source_text": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        apply_bootstrap_classes(self.fields)


class ClientContactForm(forms.ModelForm):
    class Meta:
        model = ClientContact
        fields = ("contact_type", "raw_value", "label", "comment", "is_primary")
        labels = {
            "contact_type": "Тип",
            "raw_value": "Значение",
            "label": "Подпись",
            "comment": "Комментарий",
            "is_primary": "Основной",
        }
        widgets = {
            "comment": forms.Textarea(attrs={"rows": 1}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        apply_bootstrap_classes(self.fields, small=True)
        self.fields["is_primary"].widget.attrs.setdefault("class", "form-check-input")

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        if self.cleaned_data.get("DELETE"):
            return cleaned_data
        contact_type = cleaned_data.get("contact_type")
        raw_value = cleaned_data.get("raw_value")
        if not contact_type and not raw_value and self.empty_permitted:
            return cleaned_data
        if not contact_type:
            raise ValidationError("Выберите тип контакта.")
        if not raw_value:
            raise ValidationError("Укажите значение контакта.")
        self.instance.normalized_value = normalize_contact_value(str(contact_type), str(raw_value))
        return cleaned_data


class BaseClientContactFormSet(BaseInlineFormSet):
    def clean(self) -> None:
        super().clean()
        primary_count = 0
        seen: set[tuple[str, str]] = set()
        for form in self.forms:
            if not hasattr(form, "cleaned_data") or not form.cleaned_data:
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            contact_type = form.cleaned_data.get("contact_type")
            raw_value = form.cleaned_data.get("raw_value")
            normalized_value = getattr(form.instance, "normalized_value", "")
            if not contact_type and not raw_value:
                continue
            if form.cleaned_data.get("is_primary"):
                primary_count += 1
            key = (str(contact_type), normalized_value)
            if normalized_value and key in seen:
                raise ValidationError("У клиента не может быть двух одинаковых контактов одного типа.")
            if normalized_value:
                seen.add(key)
        if primary_count > 1:
            raise ValidationError("У клиента может быть только один основной контакт.")


ClientContactFormSet = inlineformset_factory(
    Client,
    ClientContact,
    form=ClientContactForm,
    formset=BaseClientContactFormSet,
    extra=1,
    can_delete=True,
)


class ContactStringParseForm(forms.Form):
    source_text = forms.CharField(
        label="Исходная строка",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )


def apply_bootstrap_classes(
    fields: dict[str, forms.Field],
    *,
    small: bool = False,
) -> None:
    control_class = "form-control form-control-sm" if small else "form-control"
    select_class = "form-select form-select-sm" if small else "form-select"

    for field in fields.values():
        if isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs.setdefault("class", "form-check-input")
        elif isinstance(field.widget, forms.Select):
            field.widget.attrs.setdefault("class", select_class)
        else:
            field.widget.attrs.setdefault("class", control_class)

