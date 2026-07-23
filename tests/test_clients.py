from __future__ import annotations

from decimal import Decimal
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clients.models import Client, ClientContact, ContactType
from apps.clients.services.contact_normalizer import normalize_contact_value
from apps.clients.services.contact_parser import parse_contact_string
from apps.clients.services.duplicate_finder import find_potential_duplicates
from apps.clients.services.phone_normalizer import normalize_phone
from apps.orders.models import Order, OrderStatus


class ClientServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        User = get_user_model()
        cls.user = User.objects.create_user(username="clients-user")

    def create_client(self, **kwargs: object) -> Client:
        data = {"display_name": "Клиент", "created_by": self.user}
        data.update(kwargs)
        return Client.objects.create(**data)

    def test_client_can_be_created_without_name_when_contact_exists(self) -> None:
        client = self.create_client(display_name="")
        contact = ClientContact.objects.create(
            client=client,
            contact_type=ContactType.PHONE,
            raw_value="8 926 070 43-18",
            is_primary=True,
        )

        self.assertEqual(client.display_name, "")
        self.assertEqual(contact.normalized_value, "+79260704318")

    def test_preferred_channel_can_exist_without_contact(self) -> None:
        client = self.create_client(
            display_name="Индира",
            preferred_channel=ContactType.MAX,
            source_text="Индира мах",
        )

        self.assertEqual(client.preferred_channel, ContactType.MAX)
        self.assertEqual(client.contacts.count(), 0)

    def test_client_can_have_multiple_contacts_and_one_primary(self) -> None:
        client = self.create_client()
        ClientContact.objects.create(client=client, contact_type=ContactType.PHONE, raw_value="8916985 25-70", is_primary=True)
        ClientContact.objects.create(client=client, contact_type=ContactType.TELEGRAM, raw_value="@Erina197")

        self.assertEqual(client.contacts.count(), 2)
        self.assertEqual(client.contacts.filter(is_primary=True).count(), 1)

    def test_client_cannot_have_two_primary_contacts(self) -> None:
        client = self.create_client()
        ClientContact.objects.create(client=client, contact_type=ContactType.PHONE, raw_value="8916985 25-70", is_primary=True)

        with self.assertRaises(ValidationError):
            ClientContact.objects.create(client=client, contact_type=ContactType.WHATSAPP, raw_value="8 926 070 43-18", is_primary=True)

    def test_raw_value_is_preserved_and_normalized_value_is_generated(self) -> None:
        contact = ClientContact.objects.create(
            client=self.create_client(),
            contact_type=ContactType.PHONE,
            raw_value="8 926 070 43-18",
        )

        self.assertEqual(contact.raw_value, "8 926 070 43-18")
        self.assertEqual(contact.normalized_value, "+79260704318")

    def test_duplicate_contact_inside_one_client_is_rejected(self) -> None:
        client = self.create_client()
        ClientContact.objects.create(client=client, contact_type=ContactType.PHONE, raw_value="8 926 070 43-18")

        with self.assertRaises(ValidationError):
            ClientContact.objects.create(client=client, contact_type=ContactType.PHONE, raw_value="+7 926 070-43-18")

    def test_same_contact_for_different_clients_is_allowed(self) -> None:
        first = self.create_client(display_name="Первый")
        second = self.create_client(display_name="Второй")

        ClientContact.objects.create(client=first, contact_type=ContactType.PHONE, raw_value="8 926 070 43-18")
        contact = ClientContact.objects.create(client=second, contact_type=ContactType.PHONE, raw_value="+7 926 070-43-18")

        self.assertEqual(contact.normalized_value, "+79260704318")

    def test_clients_are_not_merged_by_name(self) -> None:
        self.create_client(display_name="Ирина")
        self.create_client(display_name="Ирина")

        self.assertEqual(Client.objects.filter(display_name="Ирина").count(), 2)

    def test_russian_phone_normalization(self) -> None:
        cases = {
            "8 926 070 43-18": "+79260704318",
            "7 991 288-82-81": "+79912888281",
            "+7 977 373-09-48": "+79773730948",
            "8916985 25-70": "+79169852570",
        }
        for raw_value, expected in cases.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(normalize_phone(raw_value), expected)

    def test_invalid_phone_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            normalize_phone("12345")

    def test_international_phone_keeps_country_code(self) -> None:
        self.assertEqual(normalize_phone("+37455212261"), "+37455212261")
        self.assertNotEqual(normalize_phone("+37455212261")[:2], "+7")

    def test_telegram_normalization(self) -> None:
        self.assertEqual(normalize_contact_value(ContactType.TELEGRAM, "@Erina197"), "erina197")
        self.assertEqual(normalize_contact_value(ContactType.TELEGRAM, "t.me/Erina197"), "erina197")
        self.assertEqual(normalize_contact_value(ContactType.TELEGRAM, "https://t.me/Erina197"), "erina197")

    def test_whatsapp_normalization_uses_phone(self) -> None:
        self.assertEqual(normalize_contact_value(ContactType.WHATSAPP, "7 991 288-82-81"), "+79912888281")

    def test_max_markers_are_strict_tokens(self) -> None:
        marker_cases = ["Индира мах", "НАСТЯ, макс", "(max)", "max: @username"]
        for value in marker_cases:
            with self.subTest(value=value):
                self.assertEqual(parse_contact_string(value).preferred_channel, ContactType.MAX)

        non_marker_cases = ["Максим", "максим", "Максимов", "максимальный", "maximum", "xmax"]
        for value in non_marker_cases:
            with self.subTest(value=value):
                self.assertNotEqual(parse_contact_string(value).preferred_channel, ContactType.MAX)

    def test_parser_handles_required_examples(self) -> None:
        examples = [
            ("7 991 288-82-81 WA", "", ContactType.WHATSAPP, ContactType.WHATSAPP, "+79912888281"),
            ("+7 977 373-09-48", "", "", ContactType.PHONE, "+79773730948"),
            ("+7-916-080-41-11 макс НАСТЯ", "НАСТЯ", ContactType.MAX, ContactType.MAX, "+79160804111"),
            ("8 926 070 43-18 Irina Kuptsova Tg", "Irina Kuptsova", ContactType.TELEGRAM, ContactType.TELEGRAM, "+79260704318"),
            ("@Erina197", "", ContactType.TELEGRAM, ContactType.TELEGRAM, "erina197"),
            ("максим стрельцов 8916985 25-70", "максим стрельцов", "", ContactType.PHONE, "+79169852570"),
            ("+37455212261", "", "", ContactType.PHONE, "+37455212261"),
        ]
        for source_text, name, channel, contact_type, normalized in examples:
            with self.subTest(source_text=source_text):
                parsed = parse_contact_string(source_text)
                self.assertEqual(parsed.display_name, name)
                self.assertEqual(parsed.preferred_channel, channel)
                self.assertEqual(parsed.contacts[0].contact_type, contact_type)
                self.assertEqual(parsed.contacts[0].normalized_value, normalized)
                self.assertEqual(parsed.source_text, source_text)

    def test_parser_handles_max_without_specific_contact(self) -> None:
        parsed = parse_contact_string("Индира мах")

        self.assertEqual(parsed.display_name, "Индира")
        self.assertEqual(parsed.preferred_channel, ContactType.MAX)
        self.assertEqual(parsed.contacts, [])
        self.assertIn("Указан канал MAX", parsed.warnings[0])

    def test_parser_does_not_write_to_database(self) -> None:
        before = Client.objects.count()

        parse_contact_string("+7-916-080-41-11 макс НАСТЯ")

        self.assertEqual(Client.objects.count(), before)

    def test_duplicate_finder_detects_strong_medium_and_weak_matches(self) -> None:
        first = self.create_client(display_name="Ирина")
        ClientContact.objects.create(client=first, contact_type=ContactType.PHONE, raw_value="8 926 070 43-18")
        second = self.create_client(display_name="Другой")
        ClientContact.objects.create(client=second, contact_type=ContactType.WHATSAPP, raw_value="8 926 070 43-18")

        matches = find_potential_duplicates(
            display_name="Ирина",
            contacts=[{"contact_type": ContactType.PHONE, "normalized_value": "+79260704318"}],
        )

        strengths = {match.strength for match in matches}
        self.assertIn("strong", strengths)
        self.assertIn("medium", strengths)
        self.assertIn("weak", strengths)


class ClientInterfaceTests(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        User = get_user_model()
        cls.user = User.objects.create_user(username="client-ui")
        cls.no_permission_user = User.objects.create_user(username="client-no-perm")
        permissions = Permission.objects.filter(
            content_type__app_label__in=("clients", "orders"),
            codename__in=("add_client", "view_client", "change_client", "add_order", "view_order", "change_order"),
        )
        cls.user.user_permissions.add(*permissions)

    def client_form_data(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "display_name": "Irina Kuptsova",
            "preferred_channel": ContactType.TELEGRAM,
            "comment": "Писать вечером",
            "source_text": "8 926 070 43-18 Irina Kuptsova Tg",
            "contacts-TOTAL_FORMS": "2",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "contacts-0-contact_type": ContactType.TELEGRAM,
            "contacts-0-raw_value": "8 926 070 43-18",
            "contacts-0-label": "основной",
            "contacts-0-comment": "",
            "contacts-0-is_primary": "on",
            "contacts-1-contact_type": ContactType.EMAIL,
            "contacts-1-raw_value": "IRINA@example.com",
            "contacts-1-label": "",
            "contacts-1-comment": "",
        }
        data.update(overrides)
        return data

    def create_client_with_contact(self) -> Client:
        client = Client.objects.create(display_name="Irina Kuptsova", created_by=self.user)
        ClientContact.objects.create(
            client=client,
            contact_type=ContactType.TELEGRAM,
            raw_value="8 926 070 43-18",
            is_primary=True,
        )
        return client

    def create_order(self, **kwargs: object) -> Order:
        data = {
            "order_date": timezone.localdate(),
            "status": OrderStatus.ACCEPTED,
            "work_information": "Фото",
            "contacts": "старый снимок",
            "total_amount": Decimal("100.00"),
            "advance_amount": Decimal("0.00"),
            "additional_payment": Decimal("0.00"),
            "created_by": self.user,
        }
        data.update(kwargs)
        return Order.objects.create(**data)

    def order_form_data(self, **overrides: object) -> dict[str, object]:
        data: dict[str, object] = {
            "order_date": timezone.localdate().isoformat(),
            "status": OrderStatus.ACCEPTED,
            "client": "",
            "order_number": "",
            "work_information": "Фото",
            "contacts": "+7 916 080-41-11",
            "total_amount": "100.00",
            "advance_amount": "0.00",
            "additional_payment": "0.00",
            "comment": "",
        }
        data.update(overrides)
        return data

    def test_user_with_view_permission_sees_client_list(self) -> None:
        self.client.force_login(self.user)

        response = self.client.get(reverse("clients:list"))

        self.assertEqual(response.status_code, 200)

    def test_client_list_partial_returns_rows_for_infinite_scroll(self) -> None:
        for index in range(30):
            Client.objects.create(display_name=f"Клиент {index:02d}", created_by=self.user)
        self.client.force_login(self.user)

        response = self.client.get(reverse("clients:list"), {"page": "2", "partial": "1"})

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "clients/_client_rows.html")
        self.assertContains(response, "<tr")
        self.assertNotContains(response, "<h1")

    def test_authenticated_user_without_permissions_can_see_client_list(self) -> None:
        self.client.force_login(self.no_permission_user)

        response = self.client.get(reverse("clients:list"))

        self.assertEqual(response.status_code, 200)

    def test_user_with_add_permission_can_create_client_with_multiple_contacts(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(reverse("clients:create"), data=self.client_form_data())

        client = Client.objects.get(display_name="Irina Kuptsova")
        self.assertRedirects(response, client.get_absolute_url())
        self.assertEqual(client.created_by, self.user)
        self.assertEqual(client.contacts.count(), 2)
        self.assertEqual(client.contacts.get(contact_type=ContactType.EMAIL).normalized_value, "irina@example.com")

    def test_form_error_keeps_entered_data(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("clients:create"),
            data=self.client_form_data(
                **{
                    "contacts-0-contact_type": ContactType.PHONE,
                    "contacts-0-raw_value": "12345",
                }
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Irina Kuptsova")
        self.assertContains(response, "12345")

    def test_archive_and_restore_client(self) -> None:
        client = self.create_client_with_contact()
        self.client.force_login(self.user)

        self.client.post(reverse("clients:archive_item", args=[client.pk]))
        client.refresh_from_db()
        self.assertTrue(client.archived)
        self.assertNotContains(self.client.get(reverse("clients:list")), "Irina Kuptsova")
        self.assertContains(self.client.get(reverse("clients:archive")), "Irina Kuptsova")

        self.client.post(reverse("clients:restore", args=[client.pk]))
        client.refresh_from_db()
        self.assertFalse(client.archived)

    def test_search_by_name_raw_normalized_phone_and_telegram_case(self) -> None:
        self.create_client_with_contact()
        self.client.force_login(self.user)

        for query in ("Irina", "8 926", "89260704318", "+79260704318"):
            with self.subTest(query=query):
                response = self.client.get(reverse("clients:list"), {"q": query})
                self.assertContains(response, "Irina Kuptsova")

        telegram_client = Client.objects.create(display_name="Telegram User", created_by=self.user)
        ClientContact.objects.create(client=telegram_client, contact_type=ContactType.TELEGRAM, raw_value="@Erina197")
        response = self.client.get(reverse("clients:list"), {"q": "@ERINA197"})
        self.assertContains(response, "Telegram User")

    def test_client_detail_shows_contacts_source_text_and_orders(self) -> None:
        client = self.create_client_with_contact()
        client.source_text = "8 926 070 43-18 Irina Kuptsova Tg"
        client.preferred_channel = ContactType.TELEGRAM
        client.save()
        self.create_order(client=client, contacts="снимок")
        self.client.force_login(self.user)

        response = self.client.get(client.get_absolute_url())

        self.assertContains(response, "Telegram")
        self.assertContains(response, "8 926 070 43-18")
        self.assertContains(response, "Заказ")
        self.assertContains(response, "8 926 070 43-18 Irina Kuptsova Tg")

    def test_parse_preview_does_not_create_client_until_confirmation(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(reverse("clients:parse"), {"source_text": "+7-916-080-41-11 макс НАСТЯ"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "НАСТЯ")
        self.assertEqual(Client.objects.count(), 0)

    def test_confirm_parse_creates_client(self) -> None:
        self.client.force_login(self.user)
        data = self.client_form_data(
            display_name="НАСТЯ",
            preferred_channel=ContactType.MAX,
            source_text="+7-916-080-41-11 макс НАСТЯ",
            **{
                "contacts-0-contact_type": ContactType.MAX,
                "contacts-0-raw_value": "+7-916-080-41-11",
                "contacts-1-contact_type": "",
                "contacts-1-raw_value": "",
            },
        )

        response = self.client.post(reverse("clients:parse_confirm"), data=data)

        client = Client.objects.get(display_name="НАСТЯ")
        self.assertRedirects(response, client.get_absolute_url())
        self.assertEqual(client.contacts.get().normalized_value, "+79160804111")

    def test_order_client_can_be_null(self) -> None:
        order = self.create_order(client=None)

        self.assertIsNone(order.client)

    def test_order_creation_from_client_prefills_contact_snapshot(self) -> None:
        client = self.create_client_with_contact()
        self.client.force_login(self.user)

        response = self.client.get(reverse("orders:create"), {"client": client.pk})

        self.assertContains(response, "8 926 070 43-18")

    def test_order_create_with_client_and_empty_contacts_uses_snapshot(self) -> None:
        client = self.create_client_with_contact()
        self.client.force_login(self.user)
        data = {
            "order_date": timezone.localdate().isoformat(),
            "status": OrderStatus.ACCEPTED,
            "client": client.pk,
            "order_number": "",
            "work_information": "Фото",
            "contacts": "",
            "total_amount": "100.00",
            "advance_amount": "0.00",
            "additional_payment": "0.00",
            "comment": "",
        }

        response = self.client.post(reverse("orders:create"), data=data)

        order = Order.objects.get(client=client)
        self.assertRedirects(response, reverse("orders:list"))
        self.assertEqual(order.contacts, "Irina Kuptsova\n8 926 070 43-18")

    def test_new_order_with_concrete_contact_creates_client_automatically(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("orders:create"),
            data=self.order_form_data(contacts="Erina @Erina197"),
        )

        order = Order.objects.get(contacts="Erina @Erina197")
        self.assertRedirects(response, reverse("orders:list"))
        self.assertIsNotNone(order.client)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(order.client.contacts.get().normalized_value, "erina197")

    def test_new_order_with_existing_contact_links_existing_client_automatically(self) -> None:
        client = Client.objects.create(display_name="Erina", created_by=self.user)
        ClientContact.objects.create(
            client=client,
            contact_type=ContactType.TELEGRAM,
            raw_value="@erina197",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("orders:create"),
            data=self.order_form_data(contacts="Erina https://t.me/ERINA197"),
        )

        order = Order.objects.get(original_contacts="Erina https://t.me/ERINA197")
        self.assertRedirects(response, reverse("orders:list"))
        self.assertEqual(order.client, client)
        self.assertEqual(order.contacts, "Erina\n@erina197")
        self.assertEqual(order.original_contacts, "Erina https://t.me/ERINA197")
        self.assertEqual(client.contacts.count(), 1)

    def test_new_order_with_existing_contact_uses_full_client_snapshot(self) -> None:
        client = Client.objects.create(
            display_name="НАСТЯ",
            preferred_channel=ContactType.TELEGRAM,
            created_by=self.user,
        )
        ClientContact.objects.create(
            client=client,
            contact_type=ContactType.PHONE,
            raw_value="+7-916-080-41-11",
        )
        ClientContact.objects.create(
            client=client,
            contact_type=ContactType.TELEGRAM,
            raw_value="@nastya",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("orders:create"),
            data=self.order_form_data(contacts="НАСТЯ 89160804111"),
        )

        order = Order.objects.get(original_contacts="НАСТЯ 89160804111")
        self.assertRedirects(response, reverse("orders:list"))
        self.assertEqual(order.client, client)
        self.assertEqual(order.original_contacts, "НАСТЯ 89160804111")
        self.assertIn("НАСТЯ", order.contacts)
        self.assertIn("+7-916-080-41-11", order.contacts)
        self.assertIn("@nastya", order.contacts)

    def test_new_order_with_only_phone_does_not_create_or_link_client(self) -> None:
        client = Client.objects.create(display_name="НАСТЯ", created_by=self.user)
        ClientContact.objects.create(
            client=client,
            contact_type=ContactType.PHONE,
            raw_value="+7-916-080-41-11",
        )
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("orders:create"),
            data=self.order_form_data(contacts="89160804111"),
        )

        order = Order.objects.get(contacts="89160804111")
        self.assertRedirects(response, reverse("orders:list"))
        self.assertIsNone(order.client)
        self.assertEqual(Client.objects.count(), 1)

    def test_new_order_without_concrete_contact_does_not_create_client(self) -> None:
        self.client.force_login(self.user)

        response = self.client.post(
            reverse("orders:create"),
            data=self.order_form_data(contacts="Индира мах"),
        )

        order = Order.objects.get(contacts="Индира мах")
        self.assertRedirects(response, reverse("orders:list"))
        self.assertIsNone(order.client)
        self.assertEqual(Client.objects.count(), 0)

    def test_order_contacts_snapshot_is_independent_from_client_contact_changes(self) -> None:
        client = self.create_client_with_contact()
        order = self.create_order(client=client, contacts="старый снимок")
        contact = client.contacts.get()
        contact.raw_value = "8 916 985 25-70"
        contact.save()
        order.refresh_from_db()

        self.assertEqual(order.contacts, "старый снимок")

    def test_order_detail_shows_client_link_snapshot_and_actual_contacts(self) -> None:
        client = self.create_client_with_contact()
        order = self.create_order(client=client, contacts="снимок заказа")
        self.client.force_login(self.user)

        response = self.client.get(order.get_absolute_url())

        self.assertContains(response, client.get_absolute_url())
        self.assertContains(response, "снимок заказа")
        self.assertContains(response, "+7 926 070-43-18")

    def test_order_detail_shows_resolve_client_button_when_client_is_missing(self) -> None:
        order = self.create_order(contacts="+7-916-080-41-11 макс НАСТЯ")
        self.client.force_login(self.user)

        response = self.client.get(order.get_absolute_url())

        self.assertContains(response, "Создать/определить клиента")

    def test_resolve_client_from_order_creates_new_client_when_no_contact_matches(self) -> None:
        order = self.create_order(contacts="+7-916-080-41-11 макс НАСТЯ")
        self.client.force_login(self.user)

        response = self.client.post(reverse("orders:resolve_client", args=[order.pk]))

        order.refresh_from_db()
        client = order.client
        self.assertRedirects(response, order.get_absolute_url())
        self.assertIsNotNone(client)
        self.assertEqual(client.display_name, "НАСТЯ")
        self.assertEqual(client.preferred_channel, ContactType.MAX)
        self.assertEqual(client.source_text, "+7-916-080-41-11 макс НАСТЯ")
        self.assertEqual(client.contacts.get().contact_type, ContactType.MAX)
        self.assertEqual(client.contacts.get().normalized_value, "+79160804111")

    def test_resolve_client_from_order_links_existing_client_by_normalized_phone(self) -> None:
        client = Client.objects.create(display_name="", created_by=self.user)
        ClientContact.objects.create(
            client=client,
            contact_type=ContactType.PHONE,
            raw_value="8 916 080 41 11",
            is_primary=True,
        )
        order = self.create_order(contacts="+7-916-080-41-11 макс НАСТЯ")
        self.client.force_login(self.user)

        self.client.post(reverse("orders:resolve_client", args=[order.pk]))

        order.refresh_from_db()
        client.refresh_from_db()
        self.assertEqual(order.client, client)
        self.assertEqual(order.original_contacts, "+7-916-080-41-11 макс НАСТЯ")
        self.assertIn("НАСТЯ", order.contacts)
        self.assertEqual(client.display_name, "НАСТЯ")
        self.assertEqual(client.preferred_channel, ContactType.MAX)
        self.assertEqual(client.contacts.count(), 1)

    def test_resolve_client_from_order_adds_missing_contact_to_existing_client(self) -> None:
        client = Client.objects.create(display_name="Ирина", created_by=self.user)
        ClientContact.objects.create(client=client, contact_type=ContactType.PHONE, raw_value="8 926 070 43-18")
        order = self.create_order(contacts="Ирина 8 926 070 43-18 irina@example.com")
        self.client.force_login(self.user)

        self.client.post(reverse("orders:resolve_client", args=[order.pk]))

        order.refresh_from_db()
        self.assertEqual(order.client, client)
        self.assertEqual(order.original_contacts, "Ирина 8 926 070 43-18 irina@example.com")
        self.assertIn("Ирина", order.contacts)
        self.assertIn("irina@example.com", order.contacts)
        self.assertTrue(client.contacts.filter(contact_type=ContactType.EMAIL, normalized_value="irina@example.com").exists())

    def test_resolve_client_from_order_does_not_choose_between_ambiguous_clients(self) -> None:
        first = Client.objects.create(display_name="Первый", created_by=self.user)
        second = Client.objects.create(display_name="Второй", created_by=self.user)
        ClientContact.objects.create(client=first, contact_type=ContactType.PHONE, raw_value="8 926 070 43-18")
        ClientContact.objects.create(client=second, contact_type=ContactType.WHATSAPP, raw_value="8 926 070 43-18")
        order = self.create_order(contacts="8 926 070 43-18")
        self.client.force_login(self.user)

        self.client.post(reverse("orders:resolve_client", args=[order.pk]))

        order.refresh_from_db()
        self.assertIsNone(order.client)
        self.assertEqual(Client.objects.count(), 2)

    def test_archived_client_is_not_available_for_new_order_choice(self) -> None:
        client = self.create_client_with_contact()
        client.archive()
        client.save()
        order = self.create_order(client=client)
        self.client.force_login(self.user)

        create_response = self.client.get(reverse("orders:create"))
        detail_response = self.client.get(order.get_absolute_url())

        self.assertNotContains(create_response, "Irina Kuptsova")
        self.assertContains(detail_response, "Irina Kuptsova")

    def test_analyze_order_contacts_is_safe_and_can_write_csv(self) -> None:
        client = self.create_client_with_contact()
        order = self.create_order(contacts="8 926 070 43-18 Irina Kuptsova Tg")
        with TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "report.csv"
            call_command("analyze_order_contacts", "--csv", csv_path, stdout=StringIO())
            order.refresh_from_db()
            self.assertIsNone(order.client)
            self.assertTrue(csv_path.exists())
            self.assertIn("order_id", csv_path.read_text(encoding="utf-8-sig"))

            call_command("analyze_order_contacts", "--csv", csv_path, "--apply-safe", stdout=StringIO())
            order.refresh_from_db()
            self.assertEqual(order.client, client)

        self.assertEqual(Client.objects.filter(pk=client.pk).count(), 1)

    def test_resolve_order_clients_command_creates_links_and_skips_non_concrete_contacts(self) -> None:
        existing_client = Client.objects.create(display_name="", created_by=self.user)
        ClientContact.objects.create(
            client=existing_client,
            contact_type=ContactType.PHONE,
            raw_value="8 916 080 41 11",
        )
        order_for_existing = self.create_order(contacts="+7-916-080-41-11 макс НАСТЯ")
        order_for_new_client = self.create_order(contacts="Erina @Erina197")
        order_without_concrete_contact = self.create_order(contacts="Индира мах")
        order_with_only_phone = self.create_order(contacts="89160804111")

        call_command("resolve_order_clients", "--created-by", self.user.username, stdout=StringIO())

        order_for_existing.refresh_from_db()
        order_for_new_client.refresh_from_db()
        order_without_concrete_contact.refresh_from_db()
        order_with_only_phone.refresh_from_db()
        existing_client.refresh_from_db()

        self.assertEqual(order_for_existing.client, existing_client)
        self.assertEqual(existing_client.display_name, "НАСТЯ")
        self.assertEqual(existing_client.preferred_channel, ContactType.MAX)
        self.assertEqual(existing_client.contacts.count(), 1)
        self.assertIsNotNone(order_for_new_client.client)
        self.assertEqual(order_for_new_client.client.contacts.get().normalized_value, "erina197")
        self.assertIsNone(order_without_concrete_contact.client)
        self.assertIsNone(order_with_only_phone.client)

    def test_resolve_order_clients_dry_run_does_not_change_database(self) -> None:
        order = self.create_order(contacts="Erina @Erina197")

        call_command("resolve_order_clients", "--created-by", self.user.username, "--dry-run", stdout=StringIO())

        order.refresh_from_db()
        self.assertIsNone(order.client)
        self.assertEqual(Client.objects.count(), 0)
