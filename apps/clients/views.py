from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.clients.forms import ClientContactFormSet, ClientForm, ContactStringParseForm
from apps.clients.models import Client, ClientContact
from apps.clients.services.contact_normalizer import normalize_username
from apps.clients.services.contact_parser import parse_contact_string
from apps.clients.services.duplicate_finder import find_potential_duplicates
from apps.clients.services.phone_normalizer import try_normalize_phone


class ClientPermissionMixin(LoginRequiredMixin):
    pass


class ClientListView(ClientPermissionMixin, ListView):
    model = Client
    template_name = "clients/client_list.html"
    partial_template_name = "clients/_client_rows.html"
    context_object_name = "clients"
    paginate_by = 25
    permission_required = "clients.view_client"
    archived = False
    page_title = "Клиенты"

    def get_template_names(self) -> list[str]:
        if self.request.GET.get("partial") == "1":
            return [self.partial_template_name]
        return [self.template_name]

    def get_queryset(self):
        queryset = (
            Client.objects.filter(archived=self.archived)
            .prefetch_related("contacts")
            .annotate(
                contacts_count=Count("contacts", distinct=True),
                orders_count=Count("orders", distinct=True),
                last_order_date=Max("orders__order_date"),
            )
            .order_by("display_name", "-created_at")
        )
        query = self.request.GET.get("q", "").strip()
        if query:
            search_filter = (
                Q(display_name__icontains=query)
                | Q(comment__icontains=query)
                | Q(source_text__icontains=query)
                | Q(contacts__raw_value__icontains=query)
                | Q(contacts__normalized_value__icontains=query.lower().lstrip("@"))
            )
            normalized_phone = try_normalize_phone(query)
            if normalized_phone:
                search_filter |= Q(contacts__normalized_value=normalized_phone)
            if query.startswith("@"):
                try:
                    search_filter |= Q(contacts__normalized_value=normalize_username(query))
                except Exception:
                    pass
            queryset = queryset.filter(search_filter).distinct()
        return queryset

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["is_archive_view"] = self.archived
        context["filters"] = {"q": self.request.GET.get("q", "")}
        context["infinite_next_url"] = self.get_infinite_next_url(context)
        return context

    def get_infinite_next_url(self, context: dict[str, object]) -> str:
        page_obj = context.get("page_obj")
        if not page_obj or not page_obj.has_next():
            return ""
        params = self.request.GET.copy()
        params["page"] = page_obj.next_page_number()
        params["partial"] = "1"
        return f"{self.request.path}?{params.urlencode()}"


class ClientArchiveListView(ClientListView):
    archived = True
    page_title = "Архив клиентов"


class ClientDetailView(ClientPermissionMixin, DetailView):
    model = Client
    template_name = "clients/client_detail.html"
    context_object_name = "client"
    permission_required = "clients.view_client"

    def get_queryset(self):
        return Client.objects.select_related("created_by").prefetch_related(
            "contacts",
            "orders",
        )


class ClientEditMixin(ClientPermissionMixin, View):
    template_name = "clients/client_form.html"
    client: Client | None = None
    page_title = ""
    submit_label = "Сохранить"

    def get_client(self) -> Client:
        if self.client is None:
            self.client = Client()
        return self.client

    def get(self, request, *args: object, **kwargs: object):
        client = self.get_client()
        form = ClientForm(instance=client)
        formset = ClientContactFormSet(instance=client, prefix="contacts")
        return self.render_form(form, formset)

    def post(self, request, *args: object, **kwargs: object):
        client = self.get_client()
        form = ClientForm(request.POST, instance=client)
        formset = ClientContactFormSet(request.POST, instance=client, prefix="contacts")
        if form.is_valid() and formset.is_valid():
            client = form.save(commit=False)
            if not client.pk:
                client.created_by = request.user
            client.save()
            formset.instance = client
            formset.save()
            self.add_contact_warnings(client)
            messages.success(request, "Клиент сохранён.")
            return redirect(client.get_absolute_url())
        return self.render_form(form, formset)

    def render_form(self, form: ClientForm, formset: ClientContactFormSet):
        return render(
            self.request,
            self.template_name,
            {
                "form": form,
                "formset": formset,
                "page_title": self.page_title,
                "submit_label": self.submit_label,
                "client": self.get_client(),
            },
        )

    def add_contact_warnings(self, client: Client) -> None:
        if not client.contacts.exists():
            messages.warning(self.request, "Клиент сохранён без контактных данных.")
        contacts = [
            {"contact_type": contact.contact_type, "normalized_value": contact.normalized_value}
            for contact in client.contacts.all()
        ]
        for duplicate in find_potential_duplicates(
            display_name=client.display_name,
            contacts=contacts,
            exclude_client=client,
        ):
            messages.warning(
                self.request,
                f"Возможный дубль: {duplicate.client} ({duplicate.reason})",
            )


class ClientCreateView(ClientEditMixin):
    permission_required = "clients.add_client"
    page_title = "Создать клиента"
    submit_label = "Создать"


class ClientUpdateView(ClientEditMixin):
    permission_required = "clients.change_client"
    page_title = "Редактировать клиента"
    submit_label = "Сохранить"

    def dispatch(self, request, *args: object, **kwargs: object):
        self.client = get_object_or_404(Client, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)


class ClientArchiveView(ClientPermissionMixin, TemplateView):
    template_name = "clients/client_archive_confirm.html"
    permission_required = "clients.change_client"

    def dispatch(self, request, *args: object, **kwargs: object):
        self.client = get_object_or_404(Client, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["client"] = self.client
        return context

    def post(self, request, pk: int):
        self.client.archive()
        self.client.save()
        messages.success(request, "Клиент перенесён в архив.")
        return redirect("clients:archive")


class ClientRestoreView(ClientPermissionMixin, View):
    permission_required = "clients.change_client"

    def post(self, request, pk: int):
        client = get_object_or_404(Client, pk=pk)
        client.restore_from_archive()
        client.save()
        messages.success(request, "Клиент восстановлен из архива.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("clients:archive")


class ContactParseView(ClientPermissionMixin, View):
    permission_required = "clients.add_client"
    template_name = "clients/contact_parse.html"
    preview_template_name = "clients/contact_parse_preview.html"

    def get(self, request):
        return render(request, self.template_name, {"form": ContactStringParseForm()})

    def post(self, request):
        parse_form = ContactStringParseForm(request.POST)
        if not parse_form.is_valid():
            return render(request, self.template_name, {"form": parse_form})
        parsed = parse_contact_string(parse_form.cleaned_data["source_text"])
        client = Client(
            display_name=parsed.display_name,
            preferred_channel=parsed.preferred_channel,
            source_text=parsed.source_text,
        )
        form = ClientForm(instance=client)
        formset = ClientContactFormSet(
            instance=client,
            prefix="contacts",
            initial=[
                {
                    "contact_type": contact.contact_type,
                    "raw_value": contact.raw_value,
                    "is_primary": index == 0,
                }
                for index, contact in enumerate(parsed.contacts)
            ],
        )
        return render(
            request,
            self.preview_template_name,
            {
                "parsed": parsed,
                "form": form,
                "formset": formset,
            },
        )


class ContactParseConfirmView(ClientCreateView):
    permission_required = "clients.add_client"
    page_title = "Подтвердить создание клиента"
    submit_label = "Создать клиента"

    def get(self, request, *args: object, **kwargs: object):
        return redirect("clients:parse")
