from datetime import timedelta
from decimal import Decimal

from django.core import mail
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from agencies import customization as custom
from agencies.models import CustomField, MessageTemplate, OfferInstallment, ServiceOffer
from dossiers import services
from dossiers.models import Dossier, ServiceFee
from dossiers.tests.factories import BaseTestCase


class OfferTests(BaseTestCase):
    def make_offer(self, agency=None):
        offer = ServiceOffer.objects.create(agency=agency or self.agency, name="Pack France")
        OfferInstallment.objects.create(offer=offer, label="Acompte", amount=Decimal("250000"), due_after_days=0)
        OfferInstallment.objects.create(offer=offer, label="Solde", amount=Decimal("500000"), due_after_days=45)
        return offer

    def test_apply_offer_creates_scheduled_fees(self):
        d = self.make_dossier()
        offer = self.make_offer()
        custom.apply_offer(d, self.counselor, offer)
        fees = list(d.fees.order_by("due_date"))
        self.assertEqual([f.amount for f in fees], [Decimal("250000"), Decimal("500000")])
        self.assertEqual(fees[1].due_date, timezone.localdate() + timedelta(days=45))
        self.assertEqual(d.balance(), Decimal("750000"))
        self.assertEqual(offer.total, Decimal("750000"))

    def test_offer_from_other_agency_is_refused(self):
        d = self.make_dossier()
        foreign = self.make_offer(self.other_agency)
        with self.assertRaises(services.BusinessRuleError):
            custom.apply_offer(d, self.counselor, foreign)
        self.login(self.admin)
        resp = self.client.post(reverse("dossiers:apply_offer", args=[d.pk]), {"offer": foreign.pk})
        self.assertEqual(resp.status_code, 404)

    def test_offer_in_dossier_creation_form(self):
        offer = self.make_offer()
        self.login(self.admin)
        self.client.post(reverse("dossiers:create"), {
            "student_first_name": "Awa", "student_last_name": "Diallo", "student_email": "awa@a.ml",
            "workflow": self.workflow.pk, "offer": offer.pk})
        d = Dossier.objects.get(student__email="awa@a.ml")
        self.assertEqual(d.fees.count(), 2)

    def test_overdue_installment_raises_alert(self):
        d = self.make_dossier()
        ServiceFee.objects.create(dossier=d, label="Acompte", amount=Decimal("1000"),
                                  due_date=timezone.localdate() - timedelta(days=2))
        self.assertIn("payment_overdue", {a["code"] for a in d.alerts()})


class CustomFieldTests(BaseTestCase):
    def setUp(self):
        CustomField.objects.create(agency=self.agency, label="N° Campus France", key="campus_france", required=True)
        CustomField.objects.create(agency=self.agency, label="Niveau de français", key="niveau",
                                   field_type="choice", choices="A2\nB1\nB2", visible_to_student=True)
        CustomField.objects.create(agency=self.agency, label="Bac obtenu le", key="bac", field_type="date")

    def test_create_dossier_with_custom_fields(self):
        self.login(self.admin)
        base = {"student_first_name": "Awa", "student_last_name": "Diallo", "student_email": "awa@a.ml",
                "workflow": self.workflow.pk}
        resp = self.client.post(reverse("dossiers:create"), base)
        self.assertEqual(resp.status_code, 200)  # champ obligatoire manquant
        self.client.post(reverse("dossiers:create"), {**base, "cf_campus_france": "ML24-001", "cf_niveau": "B2",
                                                       "cf_bac": "2025-07-10"})
        d = Dossier.objects.get(student__email="awa@a.ml")
        self.assertEqual(d.custom_data, {"campus_france": "ML24-001", "niveau": "B2", "bac": "2025-07-10"})
        detail = self.client.get(reverse("dossiers:detail", args=[d.pk]))
        self.assertContains(detail, "ML24-001")
        self.assertContains(detail, "10/07/2025")
        # Seuls les champs « visibles par l'étudiant » apparaissent sur le portail.
        self.login(d.student)
        portal = self.client.get(reverse("portal:dossier", args=[d.pk]))
        self.assertContains(portal, "B2")
        self.assertNotContains(portal, "ML24-001")
        # Les exports contiennent les champs.
        self.login(self.admin)
        body = self.client.get(reverse("dossiers:export")).content.decode("utf-8-sig")
        self.assertIn("N° Campus France", body)
        self.assertIn("ML24-001", body)

    def test_invalid_choice_rejected_by_api_validation(self):
        with self.assertRaises(services.BusinessRuleError):
            custom.validate_custom_data(self.agency, {"campus_france": "X", "niveau": "C2"})
        with self.assertRaises(services.BusinessRuleError):
            custom.validate_custom_data(self.agency, {"campus_france": "X", "inconnu": "1"})
        self.assertEqual(custom.validate_custom_data(self.agency, {"campus_france": "X"}), {"campus_france": "X"})

    def test_settings_pages_create_field(self):
        self.login(self.admin)
        resp = self.client.post(reverse("agencies:field_create"), {
            "label": "Moyenne au bac", "field_type": "number", "order": 1, "is_active": "on"})
        self.assertRedirects(resp, reverse("agencies:fields"))
        self.assertTrue(CustomField.objects.filter(agency=self.agency, key="moyenne_au_bac").exists())
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("agencies:fields")).status_code, 403)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class MessageAndReceiptTests(BaseTestCase):
    def test_render_template_variables(self):
        d = self.make_dossier()
        self.add_fee(d, 300000)
        tpl = MessageTemplate.objects.create(agency=self.agency, name="Test",
                                             body="Bonjour {prenom}, solde {solde}, pièces : {pieces_manquantes} {inconnue}")
        text = custom.render_text(tpl.body, custom.message_context(d))
        self.assertIn("Bonjour Awa", text)
        self.assertIn("300", text)
        self.assertIn("{inconnue}", text)  # variable inconnue laissée telle quelle

    def test_default_templates_installed_and_email_sending(self):
        from agencies.services import create_agency

        agency, admin = create_agency(name="Agence Messages", admin_email="m@m.ml", admin_password=self.password)
        self.assertEqual(agency.message_templates.count(), 4)
        self.assertEqual(agency.subdomain, "agence-messages")
        d = self.make_dossier()
        self.login(self.counselor)
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse("dossiers:send_message", args=[d.pk]),
                             {"channel": "email", "subject": "Votre dossier", "body": "Bonjour Awa"})
        self.assertTrue(any(m.subject == "Votre dossier" for m in mail.outbox))
        resp = self.client.post(reverse("dossiers:send_message", args=[d.pk]), {"channel": "whatsapp", "body": "Salut"})
        self.assertTrue(resp["Location"].startswith("https://wa.me/"))
        self.assertEqual(d.events.filter(visible_to_student=False, message__contains="WhatsApp").count(), 1)

    def test_receipt_numbers_are_sequential_with_prefix(self):
        self.agency.receipt_prefix = "hzn"
        self.agency.legal_info = "RCCM MA.BKO.2026.B.1234"
        self.agency.save()
        d = self.make_dossier()
        self.add_fee(d, 100000)
        p1 = services.record_payment(d, self.counselor, amount=Decimal("1000"), method="cash")
        p2 = services.record_payment(d, self.counselor, amount=Decimal("1000"), method="cash")
        year = timezone.localdate().year
        self.assertEqual((p1.receipt_number, p2.receipt_number), (f"HZN-{year}-0001", f"HZN-{year}-0002"))
        self.login(d.student)
        self.assertContains(self.client.get(reverse("dossiers:receipt", args=[p1.pk])), "RCCM MA.BKO.2026.B.1234")


@override_settings(BASE_DOMAIN="neuralis-mobility.test", ALLOWED_HOSTS=[".neuralis-mobility.test", "testserver"])
class TenantTests(BaseTestCase):
    def setUp(self):
        self.agency.subdomain = "agence-a"
        self.agency.save()

    def test_branded_login_and_foreign_accounts_refused(self):
        host = {"HTTP_HOST": "agence-a.neuralis-mobility.test"}
        resp = self.client.get(reverse("accounts:login"), **host)
        self.assertContains(resp, "Agence A")
        resp = self.client.post(reverse("accounts:login"), {"username": "admin@b.ml", "password": self.password}, **host)
        self.assertContains(resp, "n&#x27;appartient pas à Agence A")
        resp = self.client.post(reverse("accounts:login"), {"username": "admin@a.ml", "password": self.password}, **host)
        self.assertEqual(resp.status_code, 302)

    def test_foreign_session_is_logged_out_on_tenant_host(self):
        self.client.force_login(self.other_admin)
        resp = self.client.get(reverse("dossiers:dashboard"), HTTP_HOST="agence-a.neuralis-mobility.test")
        self.assertRedirects(resp, reverse("accounts:login"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_portal_link_uses_subdomain(self):
        self.assertEqual(custom.portal_login_url(self.agency), "https://agence-a.neuralis-mobility.test/compte/connexion/")
