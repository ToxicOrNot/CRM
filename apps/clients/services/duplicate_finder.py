from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q

from apps.clients.models import Client, ClientContact, ContactType


PHONE_BASED_TYPES = {
    ContactType.PHONE,
    ContactType.WHATSAPP,
    ContactType.TELEGRAM,
    ContactType.MAX,
}


@dataclass
class DuplicateMatch:
    client: Client
    contact: ClientContact | None
    strength: str
    reason: str


def find_potential_duplicates(
    *,
    display_name: str = "",
    contacts: list[dict[str, str]] | None = None,
    exclude_client: Client | None = None,
) -> list[DuplicateMatch]:
    contacts = contacts or []
    matches: list[DuplicateMatch] = []
    seen: set[tuple[int, str, int | None]] = set()

    def add(client: Client, contact: ClientContact | None, strength: str, reason: str) -> None:
        key = (client.pk, strength, contact.pk if contact else None)
        if key not in seen:
            seen.add(key)
            matches.append(DuplicateMatch(client=client, contact=contact, strength=strength, reason=reason))

    contact_query = ClientContact.objects.select_related("client")
    if exclude_client and exclude_client.pk:
        contact_query = contact_query.exclude(client=exclude_client)

    for contact_data in contacts:
        contact_type = contact_data.get("contact_type", "")
        normalized_value = contact_data.get("normalized_value", "")
        if not normalized_value:
            continue
        for contact in contact_query.filter(contact_type=contact_type, normalized_value=normalized_value):
            add(contact.client, contact, "strong", "Совпадает тип и нормализованное значение контакта.")
        if normalized_value.startswith("+") and contact_type in PHONE_BASED_TYPES:
            for contact in contact_query.filter(
                normalized_value=normalized_value,
                contact_type__in=PHONE_BASED_TYPES,
            ).exclude(contact_type=contact_type):
                add(contact.client, contact, "medium", "Совпадает телефон в другом канале связи.")

    normalized_name = normalize_name(display_name)
    if normalized_name:
        client_query = Client.objects.all()
        if exclude_client and exclude_client.pk:
            client_query = client_query.exclude(pk=exclude_client.pk)
        for client in client_query:
            if normalize_name(client.display_name) == normalized_name:
                add(client, None, "weak", "Совпадает имя клиента.")

    return matches


def normalize_name(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def find_clients_for_contacts(contacts: list[dict[str, str]]) -> list[Client]:
    query = Q()
    for contact in contacts:
        normalized_value = contact.get("normalized_value", "")
        contact_type = contact.get("contact_type", "")
        if not normalized_value:
            continue
        query |= Q(contacts__contact_type=contact_type, contacts__normalized_value=normalized_value)
        if normalized_value.startswith("+") and contact_type in PHONE_BASED_TYPES:
            query |= Q(contacts__contact_type__in=PHONE_BASED_TYPES, contacts__normalized_value=normalized_value)
    if not query:
        return []
    return list(Client.objects.filter(query).distinct())
