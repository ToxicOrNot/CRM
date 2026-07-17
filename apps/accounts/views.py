from django.contrib.auth import login
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import FormView

from apps.accounts.forms import UserSelectLoginForm


class UserSelectLoginView(FormView):
    template_name = "accounts/login.html"
    form_class = UserSelectLoginForm

    def dispatch(self, request, *args: object, **kwargs: object):
        if request.user.is_authenticated:
            return redirect(self.get_success_url())
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self) -> dict[str, str]:
        initial = super().get_initial()
        initial["next"] = self.request.GET.get("next", "")
        return initial

    def form_valid(self, form: UserSelectLoginForm):
        user = form.cleaned_data["user"]
        login(
            self.request,
            user,
            backend="django.contrib.auth.backends.ModelBackend",
        )
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("dashboard")
