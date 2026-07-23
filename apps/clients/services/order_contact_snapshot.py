from __future__ import annotations

from apps.clients.models import Client, ClientContact, ContactType


def build_order_contact_snapshot(client: Client | None) -> str:
    if client is None:
        return ""

    snapshot_lines = []
    if client.display_name:
        snapshot_lines.append(client.display_name)

    contacts = list(client.contacts.all())
    if not contacts:
        return "\n".join(snapshot_lines)

    preferred_contacts = []
    if client.preferred_channel:
        preferred_contacts = [contact for contact in contacts if contact.contact_type == client.preferred_channel]

    ordered_contacts = sort_contacts(preferred_contacts) + [
        contact for contact in sort_contacts(contacts) if contact not in preferred_contacts
    ]
    snapshot_lines.extend(format_contact_line(contact) for contact in ordered_contacts)
    return "\n".join(line for line in snapshot_lines if line).strip()


def sort_contacts(contacts: list[ClientContact]) -> list[ClientContact]:
    return sorted(contacts, key=lambda contact: (not contact.is_primary, contact.pk or 0))


def format_contact_line(contact: ClientContact) -> str:
    value = contact.raw_value or contact.display_value
    if (
        contact.contact_type == ContactType.TELEGRAM
        and not contact.normalized_value.startswith("+")
        and not value.startswith("@")
    ):
        value = f"@{value}"
    return value.strip()
