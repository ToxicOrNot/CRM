from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.clients.services.contact_parser import parse_contact_string
from apps.clients.services.order_client_resolver import (
    can_create_client_from_order,
    find_matching_clients,
    resolve_order_client,
)
from apps.orders.models import Order


@dataclass
class ResolveStats:
    scanned: int = 0
    skipped_empty: int = 0
    skipped_without_client_identity: int = 0
    ambiguous: int = 0
    would_create_clients: int = 0
    would_link_existing_clients: int = 0
    created_clients: int = 0
    linked_existing_clients: int = 0
    updated_linked_clients: int = 0
    created_contacts: int = 0
    already_linked: int = 0


class Command(BaseCommand):
    help = "Создаёт или определяет клиентов из контактных строк заказов."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--created-by",
            type=str,
            default=None,
            help="Username пользователя, который будет указан создателем новых клиентов.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Показать, что будет сделано, без изменения базы.",
        )
        parser.add_argument(
            "--only-unlinked",
            action="store_true",
            help="Обрабатывать только заказы, у которых client не заполнен.",
        )

    def handle(self, *args: object, **options: object) -> None:
        user = self.get_created_by(options["created_by"])
        dry_run = bool(options["dry_run"])
        stats = ResolveStats()

        orders = Order.objects.filter(contacts__gt="").select_related("client").order_by("pk")
        if options["only_unlinked"]:
            orders = orders.filter(client__isnull=True)

        for order in orders:
            stats.scanned += 1
            if not order.contacts.strip():
                stats.skipped_empty += 1
                continue

            parsed = parse_contact_string(order.contacts)
            matching_clients = find_matching_clients(parsed)
            can_create_client = can_create_client_from_order(parsed)
            if not order.client_id and not matching_clients and not can_create_client:
                stats.skipped_without_client_identity += 1
                continue

            if dry_run:
                self.collect_dry_run_stats(
                    stats,
                    order_has_client=bool(order.client_id),
                    matching_clients_count=len(matching_clients),
                    can_create_client=can_create_client,
                )
                continue

            result = resolve_order_client(order, user=user)
            if result.ambiguous_clients:
                stats.ambiguous += 1
                continue
            if result.client is None:
                stats.skipped_without_client_identity += 1
                continue
            if result.created_client:
                stats.created_clients += 1
            elif result.linked_existing_client:
                stats.linked_existing_clients += 1
            elif order.client_id:
                stats.updated_linked_clients += 1
            stats.created_contacts += result.created_contacts

        self.print_stats(stats, dry_run=dry_run)

    @staticmethod
    def collect_dry_run_stats(
        stats: ResolveStats,
        *,
        order_has_client: bool,
        matching_clients_count: int,
        can_create_client: bool,
    ) -> None:
        if order_has_client:
            stats.already_linked += 1
        elif matching_clients_count > 1:
            stats.ambiguous += 1
        elif matching_clients_count == 1:
            stats.would_link_existing_clients += 1
        elif can_create_client:
            stats.would_create_clients += 1
        else:
            stats.skipped_without_client_identity += 1

    def get_created_by(self, username: str | None):
        User = get_user_model()
        if username:
            try:
                return User.objects.get(username=username)
            except User.DoesNotExist as exc:
                raise CommandError(f"Пользователь не найден: {username}") from exc

        user = (
            User.objects.filter(is_superuser=True).order_by("pk").first()
            or User.objects.filter(is_staff=True).order_by("pk").first()
            or User.objects.filter(is_active=True).order_by("pk").first()
        )
        if user is None:
            raise CommandError("Нет пользователя для поля created_by. Создайте пользователя или передайте --created-by.")
        return user

    def print_stats(self, stats: ResolveStats, *, dry_run: bool) -> None:
        self.stdout.write(f"Просмотрено заказов: {stats.scanned}")
        self.stdout.write(f"Пропущено пустых строк: {stats.skipped_empty}")
        self.stdout.write(
            f"Пропущено без уникального совпадения или данных для создания: {stats.skipped_without_client_identity}"
        )
        self.stdout.write(f"Неоднозначных совпадений: {stats.ambiguous}")
        if dry_run:
            self.stdout.write(f"Будет создано клиентов: {stats.would_create_clients}")
            self.stdout.write(f"Будет привязано к существующим клиентам: {stats.would_link_existing_clients}")
            self.stdout.write(f"Уже привязанных заказов с конкретными контактами: {stats.already_linked}")
            self.stdout.write(self.style.WARNING("Dry-run: база данных не изменялась."))
        else:
            self.stdout.write(f"Создано клиентов: {stats.created_clients}")
            self.stdout.write(f"Привязано к существующим клиентам: {stats.linked_existing_clients}")
            self.stdout.write(f"Дополнено уже привязанных клиентов: {stats.updated_linked_clients}")
            self.stdout.write(f"Добавлено контактов: {stats.created_contacts}")
