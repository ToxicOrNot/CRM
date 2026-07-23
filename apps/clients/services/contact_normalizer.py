from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator

from apps.clients.models import ContactType
from apps.clients.services.phone_normalizer import format_phone, looks_like_phone, normalize_phone


TELEGRAM_LINK_RE = re.compile(r"^(?:https?://)?(?:t\.me|telegram\.me)/", re.IGNORECASE)
MAX_LINK_RE = re.compile(r"^(?:https?://)?(?:max\.ru|web\.max\.ru|m\.max\.ru)/", re.IGNORECASE)
USERNAME_RE = re.compile(r"^@?[A-Za-z0-9_][A-Za-z0-9_]{2,63}$")


def normalize_spaces(value: str) -> str:
    return " ".join((value or "").strip().split())


def normalize_username(raw_value: str, *, link_re: re.Pattern[str] | None = None) -> str:
    value = (raw_value or "").strip()
    if link_re is not None:
        value = link_re.sub("", value)
    value = value.strip().strip("/")
    if value.startswith("@"):
        value = value[1:]
    value = value.split("?", 1)[0].split("/", 1)[0].strip()
    if not USERNAME_RE.match(value):
        raise ValidationError("Username указан в некорректном формате.")
    return value.lower()


def normalize_contact_value(contact_type: str, raw_value: str) -> str:
    if contact_type in {ContactType.PHONE, ContactType.WHATSAPP}:
        return normalize_phone(raw_value)
    if contact_type == ContactType.TELEGRAM:
        if looks_like_phone(raw_value):
            return normalize_phone(raw_value)
        return normalize_username(raw_value, link_re=TELEGRAM_LINK_RE)
    if contact_type == ContactType.MAX:
        if looks_like_phone(raw_value):
            return normalize_phone(raw_value)
        return normalize_username(raw_value, link_re=MAX_LINK_RE)
    if contact_type == ContactType.EMAIL:
        normalized = (raw_value or "").strip().lower()
        EmailValidator(message="Email указан в некорректном формате.")(normalized)
        return normalized
    if contact_type == ContactType.OTHER:
        normalized = normalize_spaces(raw_value)
        if not normalized:
            raise ValidationError("Укажите значение контакта.")
        return normalized
    raise ValidationError("Неизвестный тип контакта.")


def format_contact_value(contact_type: str, normalized_value: str, raw_value: str = "") -> str:
    if not normalized_value:
        return raw_value
    if contact_type in {ContactType.PHONE, ContactType.WHATSAPP}:
        return format_phone(normalized_value)
    if contact_type in {ContactType.TELEGRAM, ContactType.MAX}:
        if normalized_value.startswith("+"):
            return format_phone(normalized_value)
        return f"@{normalized_value}"
    return normalized_value

