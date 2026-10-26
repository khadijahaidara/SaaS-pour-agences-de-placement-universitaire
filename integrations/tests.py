import hashlib
import hmac
import json
from unittest import mock

from django.test import override_settings
from django.urls import reverse

from dossiers import services
from dossiers.tests.factories import BaseTestCase
from integrations import delivery as delivery_mod
from integrations.models import MAX_CONSECUTIVE_FAILURES, WebhookDelivery, WebhookEndpoint
from integrations.services import attempt
from integrations.tasks import retry_due_deliveries


class WebhookTests(BaseTestCase):
    def setUp(self):
        self.endpoint = WebhookEndpoint.objects.create(agency=self.agency, url="https://hooks.example.com/nm",
                                                       events=["dossier.created", "payment.recorded"])

    def test_events_create_signed_deliveries(self):
        sent = []

        def fake_post(url, secret, payload, *, event, delivery_id):
            sent.append((event, payload))
            return 200, "ok", "", 12

        with mock.patch.object(delivery_mod, "post", side_effect=fake_post), \
                self.captureOnCommitCallbacks(execute=True):
            d = self.make_dossier()
        self.assertEqual([e for e, _ in sent], ["dossier.created"])
        self.assertEqual(sent[0][1]["data"]["dossier"]["reference"], d.reference)
        self.assertEqual(WebhookDelivery.objects.get().status, WebhookDelivery.Status.SUCCESS)
        # Événement non abonné : aucune livraison
        with self.captureOnCommitCallbacks(execute=True):
            services.set_status(d, self.admin, "blocked", "visa en attente")
        self.assertEqual(WebhookDelivery.objects.count(), 1)

    def test_signature_matches_documentation(self):
        body = b'{"a":1}'
        header = delivery_mod.sign("whsec_x", 1700000000, body)
        expected = hmac.new(b"whsec_x", b"1700000000." + body, hashlib.sha256).hexdigest()
        self.assertEqual(header, f"t=1700000000,v1={expected}")

    def test_failures_are_retried_with_backoff_then_disable(self):
        delivery = WebhookDelivery.objects.create(endpoint=self.endpoint, event="ping", payload={})
        with mock.patch.object(delivery_mod, "post", return_value=(500, "err", "HTTP 500", 5)):
            attempt(delivery)
        delivery.refresh_from_db()
        self.assertEqual(delivery.status, WebhookDelivery.Status.PENDING)
        self.assertIsNotNone(delivery.next_attempt_at)
        self.assertEqual(retry_due_deliveries()["echecs"], 0)  # pas encore l'heure
        self.endpoint.consecutive_failures = MAX_CONSECUTIVE_FAILURES - 1
        self.endpoint.save()
        with mock.patch.object(delivery_mod, "post", return_value=(None, "", "Timeout", 10000)):
            attempt(WebhookDelivery.objects.get(pk=delivery.pk))
        self.endpoint.refresh_from_db()
        self.assertFalse(self.endpoint.is_active)
        self.assertTrue(self.admin.notifications.filter(message__contains="désactivé").exists())

    @override_settings(WEBHOOK_ALLOW_PRIVATE=False)
    def test_private_addresses_are_refused(self):
        for url in ["http://example.com/x", "https://127.0.0.1/x", "https://localhost/x", "ftp://example.com"]:
            with self.assertRaises(delivery_mod.UnsafeURL, msg=url):
                delivery_mod.validate_url(url)

    def test_webhook_pages_and_test_ping(self):
        self.login(self.admin)
        self.assertContains(self.client.get(reverse("integrations:webhooks")), "hooks.example.com")
        with mock.patch.object(delivery_mod, "post", return_value=(204, "", "", 30)):
            resp = self.client.post(reverse("integrations:webhook_test", args=[self.endpoint.pk]), follow=True)
        self.assertContains(resp, "Test reçu")
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("integrations:webhooks")).status_code, 403)

    def test_webhooks_need_pro_plan(self):
        from billing.models import Plan
        from billing.services import get_subscription

        sub = get_subscription(self.agency)
        sub.plan = Plan.objects.get(code="starter")
        sub.save()
        with mock.patch.object(delivery_mod, "post") as post, self.captureOnCommitCallbacks(execute=True):
            self.make_dossier()
        post.assert_not_called()
        self.assertEqual(WebhookDelivery.objects.count(), 0)


class ImportTests(BaseTestCase):
    def upload(self, text, name="dossiers.csv"):
        from django.core.files.uploadedfile import SimpleUploadedFile

        return SimpleUploadedFile(name, text.encode("utf-8"), content_type="text/csv")

    def test_preview_then_import(self):
        self.login(self.admin)
        csv_text = ("Prénom;Nom;Courriel;Téléphone;Parcours;Conseiller\n"
                    "Awa;Traoré;awa@x.ml;70000000;Maroc;conseiller@a.ml\n"
                    "Ali;Coulibaly;pas-un-courriel;;Maroc;\n"
                    "Sira;Diallo;sira@x.ml;;Atlantide;\n")
        resp = self.client.post(reverse("dossiers:import"), {"file": self.upload(csv_text)})
        self.assertContains(resp, "Courriel invalide")
        self.assertContains(resp, "Atlantide")
        self.assertContains(resp, "Importer 1 dossier")
        resp = self.client.post(reverse("dossiers:import_confirm"))
        self.assertRedirects(resp, reverse("dossiers:list"), fetch_redirect_response=False)
        d = self.agency.dossiers.get(student__email="awa@x.ml")
        self.assertEqual(d.counselor, self.counselor)
        self.assertTrue(d.stages.exists())
        self.assertTrue(self.agency.audit_logs.filter(action="dossier.imported").exists())

    def test_missing_columns_are_reported(self):
        self.login(self.admin)
        resp = self.client.post(reverse("dossiers:import"), {"file": self.upload("nom,email\nA,a@a.ml\n")}, follow=True)
        self.assertContains(resp, "Colonnes obligatoires absentes")

    def test_template_download_and_permission(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("dossiers:import")).status_code, 403)
        self.login(self.admin)
        resp = self.client.get(reverse("dossiers:import_template"))
        self.assertIn("prenom;nom;email", resp.content.decode("utf-8-sig"))


class HealthAndAuditTests(BaseTestCase):
    def test_health(self):
        resp = self.client.get("/health/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(json.loads(resp.content)["status"], "ok")

    def test_document_download_and_export_are_audited(self):
        from dossiers.tests.factories import pdf

        d = self.make_dossier()
        doc = d.document_requests.first()
        f = services.submit_document(doc, self.admin, pdf())
        self.login(self.admin)
        from django.core.signals import request_finished
        from django.db import close_old_connections

        request_finished.disconnect(close_old_connections)
        try:
            resp = self.client.get(reverse("dossiers:document_download", args=[f.pk]))
            resp.close()
        finally:
            request_finished.connect(close_old_connections)
        self.client.get(reverse("dossiers:export"))
        actions = set(self.agency.audit_logs.values_list("action", flat=True))
        self.assertTrue({"document.downloaded", "dossier.exported", "dossier.created"} <= actions)
        journal = self.client.get(reverse("audit:journal"))
        self.assertContains(journal, "Pièce téléchargée")
        export = self.client.get(reverse("audit:journal_export"))
        self.assertIn("Pièce téléchargée", export.content.decode("utf-8-sig"))

    def test_journal_needs_permission(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("audit:journal")).status_code, 403)
