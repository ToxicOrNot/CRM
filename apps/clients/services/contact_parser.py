from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.core.exceptions import ValidationError

from apps.clients.models import ContactType
from apps.clients.services.contact_normalizer import (
    MAX_LINK_RE,
    TELEGRAM_LINK_RE,
    normalize_contact_value,
    normalize_spaces,
)


MAX_MARKER_RE = re.compile(r"(?<![\w])(?:макс|мах|max)(?![\w])", re.IGNORECASE)
WA_MARKER_RE = re.compile(r"(?<![\w])(?:wa|whatsapp|вотсап|ватсап|вацап)(?![\w])", re.IGNORECASE)
TG_MARKER_RE = re.compile(r"(?<![\w])(?:tg|telegram|телеграм|телега)(?![\w])", re.IGNORECASE)
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-zА-Яа-я]{2,}(?![\w.-])", re.IGNORECASE)
USERNAME_RE = re.compile(r"(?<![\w])@[A-Za-z0-9_][A-Za-z0-9_]{2,63}(?![\w])")
TELEGRAM_LINK_FIND_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/[A-Za-z0-9_][A-Za-z0-9_]{2,63}", re.IGNORECASE)
MAX_LINK_FIND_RE = re.compile(r"(?:https?://)?(?:max\.ru|web\.max\.ru|m\.max\.ru)/[A-Za-z0-9_][A-Za-z0-9_]{2,63}", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


@dataclass
class ParsedContact:
    contact_type: str
    raw_value: str
    normalized_value: str
    label: str = ""
    warnings: list[str] = field(default_factory=list)
    confidence: float = 1.0


@dataclass
class ParsedClientData:
    display_name: str
    preferred_channel: str
    contacts: list[ParsedContact]
    remaining_text: str
    warnings: list[str]
    confidence: float
    requires_confirmation: bool
    source_text: str


def has_marker(pattern: re.Pattern[str], value: str) -> bool:
    return pattern.search(value or "") is not None


def remove_spans(value: str, spans: list[tuple[int, int]]) -> str:
    if not spans:
        return value
    result: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        result.append(value[cursor:start])
        result.append(" ")
        cursor = end
    result.append(value[cursor:])
    return "".join(result)


def normalized_marker_free_text(value: str) -> str:
    value = MAX_MARKER_RE.sub(" ", value)
    value = WA_MARKER_RE.sub(" ", value)
    value = TG_MARKER_RE.sub(" ", value)
    value = re.sub(r"\s+[,.:;]\s+|\s+[,.:;]|[,.:;]\s+", " ", value)
    return normalize_spaces(value)


def choose_channel(source_text: str) -> str:
    if has_marker(MAX_MARKER_RE, source_text):
        return ContactType.MAX
    if has_marker(WA_MARKER_RE, source_text):
        return ContactType.WHATSAPP
    if has_marker(TG_MARKER_RE, source_text):
        return ContactType.TELEGRAM
    return ""


def contact_type_for_phone(source_text: str) -> str:
    channel = choose_channel(source_text)
    if channel in {ContactType.MAX, ContactType.WHATSAPP, ContactType.TELEGRAM}:
        return channel
    return ContactType.PHONE


def parse_contact_string(source_text: str) -> ParsedClientData:
    source_text = source_text or ""
    spans_to_remove: list[tuple[int, int]] = []
    contacts: list[ParsedContact] = []
    warnings: list[str] = []
    preferred_channel = choose_channel(source_text)

    def add_contact(contact_type: str, raw_value: str, span: tuple[int, int]) -> None:
        try:
            normalized = normalize_contact_value(contact_type, raw_value)
        except ValidationError as exc:
            warnings.append(f"Контакт «{raw_value}» не распознан: {'; '.join(exc.messages)}")
            spans_to_remove.append(span)
            return
        contacts.append(
            ParsedContact(
                contact_type=contact_type,
                raw_value=raw_value,
                normalized_value=normalized,
            )
        )
        spans_to_remove.append(span)

    for match in EMAIL_RE.finditer(source_text):
        add_contact(ContactType.EMAIL, match.group(0), match.span())

    for match in TELEGRAM_LINK_FIND_RE.finditer(source_text):
        add_contact(ContactType.TELEGRAM, match.group(0), match.span())
        preferred_channel = preferred_channel or ContactType.TELEGRAM

    for match in MAX_LINK_FIND_RE.finditer(source_text):
        add_contact(ContactType.MAX, match.group(0), match.span())
        preferred_channel = ContactType.MAX

    occupied = [(start, end) for start, end in spans_to_remove]
    for match in USERNAME_RE.finditer(source_text):
        if any(match.start() >= start and match.end() <= end for start, end in occupied):
            continue
        contact_type = ContactType.MAX if has_marker(MAX_MARKER_RE, source_text) else ContactType.TELEGRAM
        add_contact(contact_type, match.group(0), match.span())
        preferred_channel = ContactType.MAX if contact_type == ContactType.MAX else (preferred_channel or ContactType.TELEGRAM)

    occupied = [(start, end) for start, end in spans_to_remove]
    for match in PHONE_RE.finditer(source_text):
        if any(match.start() >= start and match.end() <= end for start, end in occupied):
            continue
        raw_value = match.group(0).strip()
        contact_type = contact_type_for_phone(source_text)
        add_contact(contact_type, raw_value, match.span())
        if contact_type != ContactType.PHONE:
            preferred_channel = contact_type

    remaining = remove_spans(source_text, spans_to_remove)
    display_name = normalized_marker_free_text(remaining)

    if preferred_channel == ContactType.MAX and not contacts:
        warnings.append("Указан канал MAX, но отсутствует номер или username.")
    if not display_name:
        warnings.append("Имя клиента не указано.")

    confidence = 0.95
    if not contacts and not preferred_channel:
        confidence = 0.4
    elif warnings:
        confidence = 0.75

    return ParsedClientData(
        display_name=display_name,
        preferred_channel=preferred_channel,
        contacts=contacts,
        remaining_text=display_name,
        warnings=warnings,
        confidence=confidence,
        requires_confirmation=bool(warnings) or confidence < 0.9,
        source_text=source_text,
    )
