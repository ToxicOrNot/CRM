from django import forms
from django.contrib.auth import get_user_model


class UserSelectField(forms.ModelChoiceField):
    def label_from_instance(self, obj: object) -> str:
        full_name = obj.get_full_name()
        return full_name or obj.username


class UserSelectLoginForm(forms.Form):
    user = UserSelectField(
        label="Пользователь",
        queryset=None,
        empty_label="Выберите пользователя",
    )
    next = forms.CharField(required=False, widget=forms.HiddenInput)

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        User = get_user_model()
        self.fields["user"].queryset = User.objects.filter(is_active=True).order_by(
            "last_name",
            "first_name",
            "username",
        )
        self.fields["user"].widget.attrs.update({"class": "form-select", "autofocus": True})
