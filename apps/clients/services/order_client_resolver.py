from __future__ import annotations

from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Q

from apps.clients.models import Client, ClientContact, ContactType
from apps.clients.services.contact_parser import ParsedClientData, parse_contact_string
from apps.clients.services.order_contact_snapshot import build_order_contact_snapshot
from apps.orders.models import Order


PHONE_BASED_TYPES = {
    ContactType.PHONE,
    ContactType.WHATSAPP,
    ContactType.TELEGRAM,
    ContactType.MAX,
}
CLIENT_NAME_MATCH_LIMIT = 2


@dataclass
class OrderClientResolveResult:
    client: Client | None
    created_client: bool = False
    linked_existing_client: bool = False
    created_contacts: int = 0
    updated_client_fields: list[str] = field(default_factory=list)
    updated_order_contacts: bool = False
    warnings: list[str] = field(default_factory=list)
    ambiguous_clients: list[Client] = field(default_factory=list)
    parsed: ParsedClientData | None = None


def resolve_order_client(order: Order, *, user: object) -> OrderClientResolveResult:
    parsed = parse_contact_string(order.contacts)
    result = OrderClientResolveResult(client=None, parsed=parsed, warnings=list(parsed.warnings))

    if not order.contacts.strip():
        result.warnings.append("В заказе нет контактной строки для разбора.")
        return result

    with transaction.atomic():
        if order.client_id:
            client = Client.objects.select_for_update().prefetch_related("contacts").get(pk=order.client_id)
        else:
            matching_clients = find_matching_clients(parsed)
            if len(matching_clients) > 1:
                result.ambiguous_clients = matching_clients
                result.warnings.append("Найдено несколько клиентов с такими контактами. Автоматическое объединение не выполнено.")
                return result
            if matching_clients:
                client = matching_clients[0]
                result.linked_existing_client = True
            else:
                if not can_create_client_from_order(parsed):
                    result.warnings.append(
                        "Для автоматического создания клиента нужны имя и телефон/TG или одновременно телефон и TG.",
                    )
                    return result
                client = Client.objects.create(
                    display_name=parsed.display_name,
                    preferred_channel=parsed.preferred_channel,
                    source_text=parsed.source_text,
                    created_by=user,
                )
                result.created_client = True

        result.client = client
        result.updated_client_fields = merge_client_fields(client, parsed)
        if should_add_missing_contacts(client, parsed, order_already_linked=bool(order.client_id), client_was_created=result.created_client):
            result.created_contacts = add_missing_contacts(client, parsed)

        order_update_fields = []
        if order.client_id != client.pk:
            order.client = client
            order_update_fields.append("client")
        if not result.created_client and sync_order_contacts_from_client(order, client):
            result.updated_order_contacts = True
            order_update_fields.extend(["contacts", "original_contacts"])
        if order_update_fields:
            order.save(update_fields=[*order_update_fields, "updated_at"])

    return result


def has_concrete_contacts(parsed: ParsedClientData) -> bool:
    return any(contact.normalized_value for contact in parsed.contacts)


def has_client_identity(parsed: ParsedClientData) -> bool:
    return can_create_client_from_order(parsed)


def can_create_client_from_order(parsed: ParsedClientData) -> bool:
    has_name = bool(parsed.display_name)
    has_phone = has_phone_contact(parsed)
    has_telegram_id = has_telegram_username(parsed)
    return (has_name and (has_phone or has_telegram_id)) or (has_phone and has_telegram_id)


def has_phone_contact(parsed: ParsedClientData) -> bool:
    return any(is_phone_contact(contact.contact_type, contact.normalized_value) for contact in parsed.contacts)


def has_telegram_username(parsed: ParsedClientData) -> bool:
    return any(
        contact.contact_type == ContactType.TELEGRAM
        and bool(contact.normalized_value)
        and not contact.normalized_value.startswith("+")
        for contact in parsed.contacts
    )


def find_matching_clients(parsed: ParsedClientData) -> list[Client]:
    clients_by_contact = find_clients_by_contacts(parsed)
    if clients_by_contact:
        return clients_by_contact
    return find_clients_by_display_name(parsed.display_name)


def find_clients_by_contacts(parsed: ParsedClientData) -> list[Client]:
    query = Q()
    for contact in parsed.contacts:
        if not contact.normalized_value:
            continue
        if is_phone_contact(contact.contact_type, contact.normalized_value):
            query |= Q(
                contacts__contact_type__in=PHONE_BASED_TYPES,
                contacts__normalized_value=contact.normalized_value,
            )
        else:
            query |= Q(
                contacts__contact_type=contact.contact_type,
                contacts__normalized_value=contact.normalized_value,
            )
    if not query:
        return []
    return list(Client.objects.filter(query).distinct().prefetch_related("contacts"))


def find_clients_by_display_name(display_name: str) -> list[Client]:
    display_name = " ".join((display_name or "").strip().split())
    if not display_name:
        return []
    clients = []
    for client in Client.objects.prefetch_related("contacts"):
        if normalize_name(client.display_name) == normalize_name(display_name):
            clients.append(client)
            if len(clients) >= CLIENT_NAME_MATCH_LIMIT:
                break
    return clients


def merge_client_fields(client: Client, parsed: ParsedClientData) -> list[str]:
    changed_fields: list[str] = []
    if parsed.display_name and not client.display_name:
        client.display_name = parsed.display_name
        changed_fields.append("display_name")
    if parsed.preferred_channel and not client.preferred_channel:
        client.preferred_channel = parsed.preferred_channel
        changed_fields.append("preferred_channel")
    if parsed.source_text and parsed.source_text not in client.source_text:
        client.source_text = append_line(client.source_text, parsed.source_text)
        changed_fields.append("source_text")
    if changed_fields:
        client.save(update_fields=[*changed_fields, "updated_at"])
    return changed_fields


def add_missing_contacts(client: Client, parsed: ParsedClientData) -> int:
    created = 0
    existing_contacts = list(client.contacts.all())
    for parsed_contact in parsed.contacts:
        if contact_exists(existing_contacts, parsed_contact.contact_type, parsed_contact.normalized_value):
            continue
        contact = ClientContact.objects.create(
            client=client,
            contact_type=parsed_contact.contact_type,
            raw_value=parsed_contact.raw_value,
            is_primary=not existing_contacts and created == 0,
        )
        existing_contacts.append(contact)
        created += 1
    if created:
        getattr(client, "_prefetched_objects_cache", {}).pop("contacts", None)
    return created


def should_add_missing_contacts(
    client: Client,
    parsed: ParsedClientData,
    *,
    order_already_linked: bool,
    client_was_created: bool,
) -> bool:
    if client_was_created or order_already_linked:
        return True
    return parsed_has_existing_client_contact(client, parsed)


def parsed_has_existing_client_contact(client: Client, parsed: ParsedClientData) -> bool:
    existing_contacts = list(client.contacts.all())
    return any(
        contact_exists(existing_contacts, parsed_contact.contact_type, parsed_contact.normalized_value)
        for parsed_contact in parsed.contacts
    )


def sync_order_contacts_from_client(order: Order, client: Client) -> bool:
    snapshot = build_order_contact_snapshot(client)
    if not snapshot or snapshot == (order.contacts or "").strip():
        return False
    if not order.original_contacts:
        order.original_contacts = order.contacts
    order.contacts = snapshot
    return True


def contact_exists(existing_contacts: list[ClientContact], contact_type: str, normalized_value: str) -> bool:
    for contact in existing_contacts:
        if not normalized_value:
            continue
        if is_phone_contact(contact_type, normalized_value) and contact.contact_type in PHONE_BASED_TYPES:
            if contact.normalized_value == normalized_value:
                return True
        elif contact.contact_type == contact_type and contact.normalized_value == normalized_value:
            return True
    return False


def is_phone_contact(contact_type: str, normalized_value: str) -> bool:
    return normalized_value.startswith("+") and contact_type in PHONE_BASED_TYPES


def normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def append_line(current_value: str, new_value: str) -> str:
    current_value = (current_value or "").strip()
    new_value = (new_value or "").strip()
    if not current_value:
        return new_value
    if not new_value or new_value in current_value.splitlines():
        return current_value
    return f"{current_value}\n{new_value}"
