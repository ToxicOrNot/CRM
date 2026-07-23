from __future__ import annotations

import csv
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.clients.services.contact_parser import ParsedClientData, parse_contact_string
from apps.clients.services.duplicate_finder import find_clients_for_contacts
from apps.orders.models import Order


CSV_COLUMNS = [
    "order_id",
    "исходная строка",
    "предполагаемое имя",
    "preferred_channel",
    "найденные контакты",
    "типы контактов",
    "normalized_value",
    "предполагаемый существующий клиент",
    "предупреждения",
    "уровень уверенности",
    "requires_confirmation",
    "можно ли применить автоматически",
]


class Command(BaseCommand):
    help = "Анализирует текстовые контакты заказов и формирует CSV-отчёт."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--csv",
            dest="csv_path",
            default="order_contacts_report.csv",
            help="Путь к CSV-отчёту.",
        )
        parser.add_argument(
            "--apply-safe",
            action="store_true",
            help="Безопасно связать заказы с однозначно найденными существующими клиентами.",
        )

    def handle(self, *args: object, **options: object) -> None:
        csv_path = Path(str(options["csv_path"]))
        apply_safe = bool(options["apply_safe"])
        rows: list[dict[str, object]] = []
        updated_orders = 0

        orders = Order.objects.filter(contacts__gt="").select_related("client").order_by("pk")
        for order in orders:
            parsed = parse_contact_string(order.contacts)
            contacts = [
                {"contact_type": contact.contact_type, "normalized_value": contact.normalized_value}
                for contact in parsed.contacts
            ]
            possible_clients = find_clients_for_contacts(contacts)
            safe_client = get_safe_client(parsed, possible_clients)
            can_apply = safe_client is not None

            if apply_safe and can_apply and order.client_id is None:
                with transaction.atomic():
                    order.client = safe_client
                    order.save(update_fields=["client", "updated_at"])
                    updated_orders += 1

            rows.append(
                {
                    "order_id": order.pk,
                    "исходная строка": order.contacts,
                    "предполагаемое имя": parsed.display_name,
                    "preferred_channel": parsed.preferred_channel,
                    "найденные контакты": "; ".join(contact.raw_value for contact in parsed.contacts),
                    "типы контактов": "; ".join(contact.contact_type for contact in parsed.contacts),
                    "normalized_value": "; ".join(contact.normalized_value for contact in parsed.contacts),
                    "предполагаемый существующий клиент": safe_client.pk if safe_client else "",
                    "предупреждения": "; ".join(parsed.warnings),
                    "уровень уверенности": f"{parsed.confidence:.2f}",
                    "requires_confirmation": parsed.requires_confirmation,
                    "можно ли применить автоматически": can_apply,
                }
            )

        with csv_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            writer.writerows(rows)

        self.stdout.write(f"Проанализировано заказов: {len(rows)}")
        self.stdout.write(f"CSV-отчёт: {csv_path}")
        if apply_safe:
            self.stdout.write(f"Связано заказов: {updated_orders}")
        else:
            self.stdout.write("База данных не изменялась.")


def get_safe_client(parsed: ParsedClientData, possible_clients: list[object]):
    if not parsed.contacts:
        return None
    if parsed.requires_confirmation:
        return None
    if len(possible_clients) != 1:
        return None
    return possible_clients[0]
