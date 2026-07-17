from django import forms

from apps.orders.models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = (
            "order_date",
            "status",
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
        apply_bootstrap_classes(self.fields)


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
