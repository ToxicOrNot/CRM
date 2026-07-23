from __future__ import annotations

import re

import phonenumbers
from django.core.exceptions import ValidationError
from phonenumbers import PhoneNumberFormat


VISUAL_PHONE_SEPARATORS_RE = re.compile(r"[\s\-().]+")


def clean_phone_for_parse(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    prefix = "+" if value.startswith("+") else ""
    cleaned = VISUAL_PHONE_SEPARATORS_RE.sub("", value)
    if prefix and not cleaned.startswith("+"):
        cleaned = f"+{cleaned.lstrip('+')}"
    return cleaned


def normalize_phone(raw_value: str) -> str:
    cleaned = clean_phone_for_parse(raw_value)
    if not cleaned:
        raise ValidationError("Укажите телефон.")

    region = None if cleaned.startswith("+") else "RU"
    try:
        number = phonenumbers.parse(cleaned, region)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("Телефон не удалось распознать.") from exc

    if not phonenumbers.is_possible_number(number) or not phonenumbers.is_valid_number(number):
        raise ValidationError("Телефон не является корректным номером.")
    return phonenumbers.format_number(number, PhoneNumberFormat.E164)


def try_normalize_phone(raw_value: str) -> str | None:
    try:
        return normalize_phone(raw_value)
    except ValidationError:
        return None


def format_phone(normalized_value: str) -> str:
    if not normalized_value:
        return ""
    try:
        number = phonenumbers.parse(normalized_value, None)
    except phonenumbers.NumberParseException:
        return normalized_value
    return phonenumbers.format_number(number, PhoneNumberFormat.INTERNATIONAL)


def looks_like_phone(value: str) -> bool:
    digits = re.sub(r"\D+", "", value or "")
    return len(digits) >= 10 or (value or "").strip().startswith("+")

