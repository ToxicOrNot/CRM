from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.files.uploadedfile import UploadedFile
from django.db.models import DecimalField, ExpressionWrapper, F, Q, TextField, Value
from django.db.models.functions import Replace
from django.http import HttpResponse, HttpResponseNotFound, HttpResponseServerError
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, TemplateView, UpdateView

from apps.clients.models import Client
from apps.clients.services.order_client_resolver import resolve_order_client
from apps.clients.services.order_contact_snapshot import build_order_contact_snapshot
from apps.orders.forms import OrderForm, OrderQuickUpdateForm
from apps.orders.models import Order, OrderAttachment, OrderStatus


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
ORDER_PHOTO_PREVIEW_LIMIT = 39

CONTACT_DIGIT_SEPARATORS = (" ", "-", "(", ")", "+", ".", "/", "\t", "\r", "\n")


def get_digits(value: str) -> str:
    return re.sub(r"\D+", "", value)


def get_normalized_contacts_expression(field_name: str = "contacts"):
    output_field = TextField()
    expression = F(field_name)
    for separator in CONTACT_DIGIT_SEPARATORS:
        expression = Replace(
            expression,
            Value(separator, output_field=output_field),
            Value("", output_field=output_field),
            output_field=output_field,
        )
    return expression


def save_order_attachments(
    order: Order,
    uploaded_files: Iterable[UploadedFile],
    uploaded_by: object,
) -> None:
    for uploaded_file in uploaded_files:
        OrderAttachment.objects.create(
            order=order,
            file=uploaded_file,
            original_name=uploaded_file.name,
            uploaded_by=uploaded_by,
        )


def prepare_order_attachment_preview(order: Order) -> None:
    attachments = list(order.attachments.all())
    photo_attachments = [attachment for attachment in attachments if attachment.is_image]
    order.attachment_count = len(attachments)
    order.photo_preview_attachments = photo_attachments[:ORDER_PHOTO_PREVIEW_LIMIT]
    order.hidden_photo_count = max(len(photo_attachments) - ORDER_PHOTO_PREVIEW_LIMIT, 0)
    order.non_photo_attachments = [
        attachment for attachment in attachments if not attachment.is_image
    ]


class OrderPermissionMixin(LoginRequiredMixin):
    pass


class OrderListView(OrderPermissionMixin, ListView):
    model = Order
    template_name = "orders/order_list.html"
    partial_template_name = "orders/_order_rows.html"
    context_object_name = "orders"
    paginate_by = 25
    permission_required = "orders.view_order"
    page_title = "Заказы"
    archived = False

    def get_template_names(self) -> list[str]:
        if self.request.GET.get("partial") == "1":
            return [self.partial_template_name]
        return [self.template_name]

    def get_queryset(self):
        queryset = (
            Order.objects.select_related("created_by", "client")
            .prefetch_related(
                "tasks",
                "tasks__assignee",
                "client__contacts",
                "attachments",
                "attachments__uploaded_by",
            )
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
                | Q(original_contacts__icontains=query)
                | Q(comment__icontains=query)
            )
            digit_query = get_digits(query)
            if digit_query:
                queryset = queryset.annotate(
                    contacts_digits=get_normalized_contacts_expression(),
                    original_contacts_digits=get_normalized_contacts_expression("original_contacts"),
                )
                search_filter |= Q(contacts_digits__contains=digit_query)
                search_filter |= Q(original_contacts_digits__contains=digit_query)
                if query.isdigit() and len(digit_query) <= 18:
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
        context["infinite_next_url"] = self.get_infinite_next_url(context)
        context["list_return_url"] = self.get_list_return_url()
        for order in context["orders"]:
            order.status_row_class = ORDER_STATUS_ROW_CLASSES.get(order.status, "")
            order.quick_update_form = OrderQuickUpdateForm(
                instance=order,
                prefix=f"order-{order.pk}",
            )
            prepare_order_attachment_preview(order)
        return context

    def get_infinite_next_url(self, context: dict[str, object]) -> str:
        page_obj = context.get("page_obj")
        if not page_obj or not page_obj.has_next():
            return ""
        params = self.request.GET.copy()
        params["page"] = page_obj.next_page_number()
        params["partial"] = "1"
        return f"{self.request.path}?{params.urlencode()}"

    def get_list_return_url(self) -> str:
        params = self.request.GET.copy()
        params.pop("page", None)
        params.pop("partial", None)
        if not params:
            return self.request.path
        return f"{self.request.path}?{params.urlencode()}"

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
        return Order.objects.select_related("created_by", "client").prefetch_related(
            "tasks",
            "tasks__assignee",
            "client__contacts",
            "attachments",
            "attachments__uploaded_by",
        )

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        prepare_order_attachment_preview(self.object)
        return context


class OrderCreateView(OrderPermissionMixin, CreateView):
    model = Order
    form_class = OrderForm
    template_name = "orders/order_form.html"
    permission_required = "orders.add_order"

    def form_valid(self, form: OrderForm):
        form.instance.created_by = self.request.user
        self.object = form.save()
        save_order_attachments(
            order=self.object,
            uploaded_files=self.request.FILES.getlist("attachments"),
            uploaded_by=self.request.user,
        )
        messages.success(self.request, "Заказ создан.")
        self.resolve_client_from_new_order()
        return redirect("orders:list")

    def resolve_client_from_new_order(self) -> None:
        result = resolve_order_client(self.object, user=self.request.user)
        if result.ambiguous_clients:
            messages.warning(
                self.request,
                "Клиент не определён автоматически: найдено несколько возможных клиентов.",
            )
            return
        if result.client is None:
            return
        if result.created_client:
            messages.info(self.request, f"Создан клиент «{result.client}» из контактов заказа.")
        elif result.linked_existing_client:
            messages.info(self.request, f"Заказ привязан к найденному клиенту «{result.client}».")
        if result.created_contacts:
            messages.info(self.request, f"Добавлено контактов клиенту: {result.created_contacts}.")
        if result.updated_order_contacts:
            messages.info(self.request, "Контакты заказа дополнены данными из карточки клиента.")

    def get_initial(self) -> dict[str, object]:
        initial = super().get_initial()
        client_id = self.request.GET.get("client")
        if client_id:
            client = Client.objects.active().prefetch_related("contacts").filter(pk=client_id).first()
            if client:
                initial["client"] = client
                initial["contacts"] = build_order_contact_snapshot(client)
        return initial

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
        response = super().form_valid(form)
        save_order_attachments(
            order=self.object,
            uploaded_files=self.request.FILES.getlist("attachments"),
            uploaded_by=self.request.user,
        )
        messages.success(self.request, "Заказ обновлен.")
        return response

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Редактировать заказ"
        context["submit_label"] = "Сохранить"
        context["attachments"] = self.object.attachments.select_related("uploaded_by")
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


class OrderResolveClientView(OrderPermissionMixin, View):
    permission_required = ("orders.change_order", "clients.add_client")

    def post(self, request, pk: int):
        order = get_object_or_404(Order, pk=pk)
        result = resolve_order_client(order, user=request.user)

        if result.ambiguous_clients:
            client_links = ", ".join(str(client) for client in result.ambiguous_clients)
            messages.error(
                request,
                f"Найдено несколько возможных клиентов: {client_links}. Выберите клиента вручную.",
            )
            return redirect(order.get_absolute_url())

        if result.client is None:
            messages.error(request, "Не удалось определить клиента из контактов заказа.")
            for warning in result.warnings:
                messages.warning(request, warning)
            return redirect(order.get_absolute_url())

        if result.created_client:
            messages.success(request, f"Создан клиент «{result.client}» и привязан к заказу.")
        elif result.linked_existing_client:
            messages.success(request, f"Заказ привязан к существующему клиенту «{result.client}».")
        else:
            messages.success(request, f"Клиент «{result.client}» привязан к заказу.")

        if result.created_contacts:
            messages.info(request, f"Добавлено контактов клиенту: {result.created_contacts}.")
        if result.updated_order_contacts:
            messages.info(request, "Контакты заказа дополнены данными из карточки клиента.")
        if result.updated_client_fields:
            messages.info(request, "Карточка клиента дополнена данными из заказа.")
        for warning in result.warnings:
            messages.warning(request, warning)
        return redirect(order.get_absolute_url())


class OrderAttachmentArchiveView(OrderPermissionMixin, View):
    def get(self, request, pk: int):
        order = get_object_or_404(
            Order.objects.prefetch_related("attachments"),
            pk=pk,
        )
        attachments = list(order.attachments.all())
        if not attachments:
            return HttpResponseNotFound("У заказа нет прикрепленных файлов.")

        archive = BytesIO()
        used_names: set[str] = set()
        with ZipFile(archive, "w", ZIP_DEFLATED) as zip_file:
            for attachment in attachments:
                if not attachment.file:
                    continue
                file_name = attachment.file.name
                if not attachment.file.storage.exists(file_name):
                    continue
                archive_name = self.get_unique_archive_name(
                    attachment.original_name or Path(file_name).name,
                    used_names,
                )
                with attachment.file.open("rb") as source:
                    zip_file.writestr(archive_name, source.read())

        if not used_names:
            return HttpResponseNotFound("Файлы заказа не найдены на сервере.")

        archive.seek(0)
        response = HttpResponse(archive.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="order-{order.pk}-files.zip"'
        return response

    @staticmethod
    def get_unique_archive_name(file_name: str, used_names: set[str]) -> str:
        clean_name = Path(file_name).name or "file"
        if clean_name not in used_names:
            used_names.add(clean_name)
            return clean_name

        stem = Path(clean_name).stem or "file"
        suffix = Path(clean_name).suffix
        counter = 2
        while True:
            candidate = f"{stem}-{counter}{suffix}"
            if candidate not in used_names:
                used_names.add(candidate)
                return candidate
            counter += 1


class OrderAttachmentPreviewView(OrderPermissionMixin, View):
    def get(self, request, pk: int):
        attachment = get_object_or_404(OrderAttachment, pk=pk)
        if not attachment.file:
            return HttpResponseNotFound("Файл заказа не найден.")
        if not attachment.is_heic_image:
            return redirect(attachment.file.url)
        if not attachment.file.storage.exists(attachment.file.name):
            return HttpResponseNotFound("Файл заказа не найден на сервере.")

        try:
            from PIL import Image, ImageOps
            from pillow_heif import register_heif_opener
        except ImportError:
            return HttpResponseServerError(
                "Для предпросмотра HEIC/HEIF установите Pillow и pillow-heif.",
            )

        register_heif_opener()
        output = BytesIO()
        try:
            with attachment.file.open("rb") as source:
                with Image.open(source) as image:
                    image = ImageOps.exif_transpose(image)
                    image.thumbnail((1600, 1600))
                    if image.mode not in {"RGB", "L"}:
                        image = image.convert("RGB")
                    image.save(output, format="JPEG", quality=86, optimize=True)
        except Exception:
            return HttpResponseServerError("Не удалось создать предпросмотр HEIC/HEIF.")

        response = HttpResponse(output.getvalue(), content_type="image/jpeg")
        response["Cache-Control"] = "private, max-age=3600"
        return response


class OrderAttachmentDeleteView(OrderPermissionMixin, View):
    def post(self, request, pk: int):
        attachment = get_object_or_404(
            OrderAttachment.objects.select_related("order"),
            pk=pk,
        )
        order = attachment.order
        file_name = attachment.original_name
        if attachment.file:
            attachment.file.delete(save=False)
        attachment.delete()
        messages.success(request, f"Файл «{file_name}» удален из заказа.")
        return redirect(self.get_success_url(order))

    def get_success_url(self, order: Order) -> str:
        next_url = self.request.POST.get("next")
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={self.request.get_host()},
            require_https=self.request.is_secure(),
        ):
            return next_url
        return order.get_absolute_url()
