from django import forms

from apps.clients.models import Client
from apps.clients.services.order_contact_snapshot import build_order_contact_snapshot
from apps.orders.models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            "order_date",
            "status",
            "client",
            "order_number",
            "work_information",
            "contacts",
            "total_amount",
            "advance_amount",
            "additional_payment",
            "comment",
        )
        labels = {
            "order_date": "Дата заказа",
            "status": "Статус",
            "client": "Клиент",
            "order_number": "Номер заказа",
            "work_information": "Информация о работе",
            "contacts": "Контакты",
            "total_amount": "Сумма к оплате",
            "advance_amount": "Аванс",
            "additional_payment": "Доплата",
            "comment": "Комментарий",
        }
        widgets = {
            "order_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "work_information": forms.Textarea(attrs={"rows": 4}),
            "contacts": forms.Textarea(attrs={"rows": 3}),
            "comment": forms.Textarea(attrs={"rows": 3}),
            "total_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "advance_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "additional_payment": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self.fields["order_date"].input_formats = ["%Y-%m-%d"]
        client_queryset = Client.objects.active().prefetch_related("contacts")
        if self.instance and self.instance.client_id:
            client_queryset = Client.objects.filter(pk=self.instance.client_id) | client_queryset
        self.fields["client"].queryset = client_queryset.distinct()
        self.fields["client"].required = False
        self.fields["contacts"].required = False
        apply_bootstrap_classes(self.fields)

    def clean(self) -> dict[str, object]:
        cleaned_data = super().clean()
        client = cleaned_data.get("client")
        contacts = (cleaned_data.get("contacts") or "").strip()
        if client and not contacts:
            contacts = build_order_contact_snapshot(client)
            cleaned_data["contacts"] = contacts
            self.instance.contacts = contacts
        if not contacts:
            self.add_error("contacts", "Укажите контактный снимок заказа.")
        return cleaned_data


class OrderQuickUpdateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            "status",
            "total_amount",
            "advance_amount",
            "additional_payment",
        )
        labels = {
            "status": "Статус",
            "total_amount": "Сумма",
            "advance_amount": "Аванс",
            "additional_payment": "Доплата",
        }
        widgets = {
            "total_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "advance_amount": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "additional_payment": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        apply_bootstrap_classes(self.fields, small=True)


def apply_bootstrap_classes(
    fields: dict[str, forms.Field],
    *,
    small: bool = False,
) -> None:
    control_class = "form-control form-control-sm" if small else "form-control"
    select_class = "form-select form-select-sm" if small else "form-select"

    for field in fields.values():
        if isinstance(field.widget, forms.Select):
            field.widget.attrs.setdefault("class", select_class)
        else:
            field.widget.attrs.setdefault("class", control_class)
