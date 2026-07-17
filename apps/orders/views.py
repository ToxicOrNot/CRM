from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import DecimalField, ExpressionWrapper, F, Q, TextField, Value
from django.db.models.functions import Replace
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.orders.forms import OrderForm, OrderQuickUpdateForm
from apps.orders.models import Order, OrderStatus


ORDER_SORT_FIELDS = {
    "order_date": "order_date",
    "delivery_date": "delivery_date",
    "total_amount": "total_amount",
    "balance": "balance_value",
}

ORDER_STATUS_ROW_CLASSES = {
    OrderStatus.ACCEPTED: "",
    OrderStatus.WAITING_RESPONSE: "order-row-waiting",
    OrderStatus.IN_PROGRESS: "order-row-in-progress",
    OrderStatus.READY: "order-row-ready",
    OrderStatus.DELIVERED: "order-row-delivered",
    OrderStatus.CANCELLED: "order-row-cancelled",
}

CONTACT_DIGIT_SEPARATORS = (" ", "-", "(", ")", "+", ".", "/", "\t", "\r", "\n")


def get_digits(value: str) -> str:
    return re.sub(r"\D+", "", value)


def get_normalized_contacts_expression():
    output_field = TextField()
    expression = F("contacts")
    for separator in CONTACT_DIGIT_SEPARATORS:
        expression = Replace(
            expression,
            Value(separator, output_field=output_field),
            Value("", output_field=output_field),
            output_field=output_field,
        )
    return expression


class OrderPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    raise_exception = True


class OrderListView(OrderPermissionMixin, ListView):
    model = Order
    template_name = "orders/order_list.html"
    context_object_name = "orders"
    paginate_by = 25
    permission_required = "orders.view_order"
    page_title = "Заказы"
    archived = False

    def get_queryset(self):
        queryset = (
            Order.objects.select_related("created_by")
            .prefetch_related("tasks", "tasks__assignee")
            .filter(archived=self.archived)
            .annotate(
                balance_value=ExpressionWrapper(
                    F("total_amount") - F("advance_amount") - F("additional_payment"),
                    output_field=DecimalField(max_digits=12, decimal_places=2),
                ),
            )
        )

        query = self.request.GET.get("q", "").strip()
        status = self.request.GET.get("status", "")
        order_date = self.request.GET.get("order_date", "")
        delivery_date = self.request.GET.get("delivery_date", "")
        overdue_only = self.request.GET.get("overdue") == "1"
        paid_only = self.request.GET.get("paid") == "1"
        unpaid_only = self.request.GET.get("unpaid") == "1"

        if query:
            search_filter = (
                Q(order_number__icontains=query)
                | Q(work_information__icontains=query)
                | Q(contacts__icontains=query)
                | Q(comment__icontains=query)
            )
            digit_query = get_digits(query)
            if digit_query:
                queryset = queryset.annotate(
                    contacts_digits=get_normalized_contacts_expression(),
                )
                search_filter |= Q(contacts_digits__contains=digit_query)
                if len(digit_query) <= 18:
                    search_filter |= Q(pk=int(digit_query))
            queryset = queryset.filter(search_filter)
        if status in OrderStatus.values:
            queryset = queryset.filter(status=status)
        if order_date:
            queryset = queryset.filter(order_date=order_date)
        if delivery_date:
            queryset = queryset.filter(delivery_date=delivery_date)
        if overdue_only:
            queryset = queryset.overdue()
        if paid_only:
            queryset = queryset.filter(balance_value=0)
        if unpaid_only:
            queryset = queryset.filter(balance_value__gt=0)

        return self.apply_sorting(queryset)

    def apply_sorting(self, queryset):
        sort = self.request.GET.get("sort", "")
        direction = self.request.GET.get("direction", "")
        if sort not in ORDER_SORT_FIELDS or direction not in {"asc", "desc"}:
            return queryset.order_by("-order_date", "-created_at")

        order_field = ORDER_SORT_FIELDS[sort]
        if direction == "desc":
            order_field = f"-{order_field}"
        return queryset.order_by(order_field, "-created_at")

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = self.page_title
        context["status_choices"] = OrderStatus.choices
        context["filters"] = {
            "q": self.request.GET.get("q", ""),
            "status": self.request.GET.get("status", ""),
            "order_date": self.request.GET.get("order_date", ""),
            "delivery_date": self.request.GET.get("delivery_date", ""),
            "overdue": self.request.GET.get("overdue") == "1",
            "paid": self.request.GET.get("paid") == "1",
            "unpaid": self.request.GET.get("unpaid") == "1",
        }
        context["sort_links"] = self.get_sort_links()
        context["is_archive_view"] = self.archived
        for order in context["orders"]:
            order.status_row_class = ORDER_STATUS_ROW_CLASSES.get(order.status, "")
            order.quick_update_form = OrderQuickUpdateForm(
                instance=order,
                prefix=f"order-{order.pk}",
            )
        return context

    def get_sort_links(self) -> dict[str, dict[str, str]]:
        current_sort = self.request.GET.get("sort", "")
        current_direction = self.request.GET.get("direction", "")
        labels = {
            "order_date": "Дата заказа",
            "delivery_date": "Дата выдачи",
            "total_amount": "Сумма",
            "balance": "Остаток",
        }
        links: dict[str, dict[str, str]] = {}
        for field, label in labels.items():
            next_direction = "asc"
            indicator = ""
            if current_sort == field and current_direction == "asc":
                next_direction = "desc"
                indicator = "↑"
            elif current_sort == field and current_direction == "desc":
                indicator = "↓"
            params = self.request.GET.copy()
            params.pop("page", None)
            params["sort"] = field
            params["direction"] = next_direction
            links[field] = {"label": label, "url": f"?{params.urlencode()}", "indicator": indicator}
        return links


class OrderArchiveListView(OrderListView):
    page_title = "Архив заказов"
    archived = True


class OrderDetailView(OrderPermissionMixin, DetailView):
    model = Order
    template_name = "orders/order_detail.html"
    context_object_name = "order"
    permission_required = "orders.view_order"

    def get_queryset(self):
        return Order.objects.select_related("created_by").prefetch_related(
            "tasks",
            "tasks__assignee",
        )


class OrderCreateView(OrderPermissionMixin, CreateView):
    model = Order
    form_class = OrderForm
    template_name = "orders/order_form.html"
    permission_required = "orders.add_order"

    def form_valid(self, form: OrderForm):
        form.instance.created_by = self.request.user
        messages.success(self.request, "Заказ создан.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Создать заказ"
        context["submit_label"] = "Создать"
        return context


class OrderUpdateView(OrderPermissionMixin, UpdateView):
    model = Order
    form_class = OrderForm
    template_name = "orders/order_form.html"
    permission_required = "orders.change_order"

    def form_valid(self, form: OrderForm):
        messages.success(self.request, "Заказ обновлен.")
        return super().form_valid(form)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Редактировать заказ"
        context["submit_label"] = "Сохранить"
        return context


class OrderQuickUpdateView(OrderPermissionMixin, View):
    permission_required = "orders.change_order"

    def post(self, request, pk: int):
        order = get_object_or_404(Order, pk=pk)
        form = OrderQuickUpdateForm(request.POST, instance=order, prefix=f"order-{order.pk}")
        if form.is_valid():
            form.save()
            messages.success(request, "Заказ обновлен.")
        else:
            messages.error(request, "Не удалось обновить заказ. Проверьте суммы и статус.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("orders:list")


class OrderArchiveView(OrderPermissionMixin, TemplateView):
    template_name = "orders/order_archive_confirm.html"
    permission_required = "orders.change_order"

    def dispatch(self, request, *args: object, **kwargs: object):
        self.order = get_object_or_404(Order, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["order"] = self.order
        return context

    def post(self, request, pk: int):
        self.order.archive()
        self.order.save()
        messages.success(request, "Заказ перенесен в архив.")
        return redirect("orders:archive")


class OrderRestoreView(OrderPermissionMixin, View):
    permission_required = "orders.change_order"

    def post(self, request, pk: int):
        order = get_object_or_404(Order, pk=pk)
        order.restore_from_archive()
        order.save()
        messages.success(request, "Заказ восстановлен из архива.")
        return redirect(self.get_success_url())

    def get_success_url(self) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return reverse("orders:archive")
