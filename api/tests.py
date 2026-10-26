from decimal import Decimal

from django.urls import reverse

from agencies.models import CustomField, OfferInstallment, ServiceOffer
from api.models import ApiKey
from dossiers.models import Dossier
from dossiers.tests.factories import BaseTestCase


class ApiTests(BaseTestCase):
    def setUp(self):
        self.key, self.raw = ApiKey.generate(agency=self.agency, name="Test", created_by=self.admin)
        self.auth = {"HTTP_AUTHORIZATION": f"Api-Key {self.raw}"}
        self.mine = self.make_dossier(email="mine@a.ml")
        self.foreign = self.make_dossier(email="x@b.ml", agency=self.other_agency, counselor=self.other_admin,
                                         workflow=self.other_agency.workflow_templates.first(), actor=self.other_admin)

    def test_requires_authentication(self):
        resp = self.client.get("/api/v1/dossiers/")
        self.assertIn(resp.status_code, (401, 403))
        self.assertEqual(self.client.get("/api/v1/dossiers/", HTTP_AUTHORIZATION="Api-Key nm_bad_key").status_code, 401)
        self.login(self.mine.student)  # un étudiant n'a pas accès à l'API
        self.assertEqual(self.client.get("/api/v1/dossiers/").status_code, 403)

    def test_list_is_scoped_to_key_agency(self):
        resp = self.client.get("/api/v1/dossiers/", **self.auth)
        self.assertEqual(resp.status_code, 200)
        refs = [d["reference"] for d in resp.json()["results"]]
        self.assertIn(self.mine.reference, refs)
        self.assertNotIn(self.foreign.reference, refs)
        self.assertEqual(self.client.get(f"/api/v1/dossiers/{self.foreign.reference}/", **self.auth).status_code, 404)
        key = ApiKey.objects.get(pk=self.key.pk)
        self.assertIsNotNone(key.last_used_at)
        self.assertNotIn(self.raw, key.key_hash)

    def test_full_flow_create_advance_pay(self):
        offer = ServiceOffer.objects.create(agency=self.agency, name="Pack Maroc")
        OfferInstallment.objects.create(offer=offer, label="Total", amount=Decimal("400000"))
        CustomField.objects.create(agency=self.agency, label="Bac", key="bac", field_type="number")
        resp = self.client.post("/api/v1/dossiers/", {
            "student_email": "api@a.ml", "student_first_name": "Api", "student_last_name": "Test",
            "workflow_id": self.workflow.pk, "offer_id": offer.pk, "custom_data": {"bac": 14.5},
            "counselor_email": "conseiller@a.ml",
        }, content_type="application/json", **self.auth)
        self.assertEqual(resp.status_code, 201, resp.content)
        data = resp.json()
        ref = data["reference"]
        self.assertEqual(data["balance"], "400000")
        self.assertEqual(data["custom_data"], {"bac": "14.5"})
        self.assertEqual(data["counselor_email"], "conseiller@a.ml")

        # Règle métier : impossible d'avancer sans pièces validées → 400 lisible.
        resp = self.client.post(f"/api/v1/dossiers/{ref}/advance/", {}, content_type="application/json", **self.auth)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], "business_rule")

        resp = self.client.post(f"/api/v1/dossiers/{ref}/payments/", {"amount": "150000", "method": "wave"},
                                content_type="application/json", **self.auth)
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Dossier.objects.get(reference=ref).balance(), Decimal("250000"))
        resp = self.client.patch(f"/api/v1/dossiers/{ref}/", {"program": "Pharmacie", "custom_data": {"bac": "abc"}},
                                 content_type="application/json", **self.auth)
        self.assertEqual(resp.status_code, 400)
        resp = self.client.patch(f"/api/v1/dossiers/{ref}/", {"program": "Pharmacie"},
                                 content_type="application/json", **self.auth)
        self.assertEqual(resp.json()["program"], "Pharmacie")
        self.assertEqual(self.client.get("/api/v1/payments/", **self.auth).json()["count"], 1)

    def test_revoked_key_and_session_scope(self):
        self.key.revoke()
        self.assertEqual(self.client.get("/api/v1/dossiers/", **self.auth).status_code, 401)
        other = self.make_dossier(email="other@a.ml", counselor=self.counselor2)
        self.login(self.counselor)  # session : un conseiller ne voit que ses dossiers
        refs = [d["reference"] for d in self.client.get("/api/v1/dossiers/").json()["results"]]
        self.assertIn(self.mine.reference, refs)
        self.assertNotIn(other.reference, refs)

    def test_schema_and_reference_endpoints(self):
        self.assertEqual(self.client.get(reverse("api:schema")).status_code, 200)
        for url in ["/api/v1/me/", "/api/v1/workflows/", "/api/v1/offers/", "/api/v1/custom-fields/"]:
            self.assertEqual(self.client.get(url, **self.auth).status_code, 200, url)

    def test_api_key_management_page(self):
        self.login(self.admin)
        resp = self.client.post(reverse("agencies:api_keys"), {"name": "Site web"})
        self.assertContains(resp, "nm_")
        key = ApiKey.objects.get(name="Site web")
        self.client.post(reverse("agencies:api_key_revoke", args=[key.pk]))
        key.refresh_from_db()
        self.assertFalse(key.is_active)
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("agencies:api_keys")).status_code, 403)
