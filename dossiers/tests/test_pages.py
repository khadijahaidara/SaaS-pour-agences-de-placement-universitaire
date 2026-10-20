from decimal import Decimal

from django.urls import reverse

from dossiers import services

from .factories import BaseTestCase


class ProfileTests(BaseTestCase):
    def test_update_profile_and_change_password(self):
        self.login(self.counselor)
        resp = self.client.post(reverse("accounts:profile"), {
            "save_profile": "1", "p-first_name": "Moussa", "p-last_name": "Diarra", "p-phone": "+223 70 00 00 00"})
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.counselor.refresh_from_db()
        self.assertEqual(self.counselor.first_name, "Moussa")
        resp = self.client.post(reverse("accounts:profile"), {
            "change_password": "1", "pw-old_password": self.password,
            "pw-new_password1": "Nouveau-Mot-2027", "pw-new_password2": "Nouveau-Mot-2027"})
        self.assertRedirects(resp, reverse("accounts:profile"))
        self.counselor.refresh_from_db()
        self.assertTrue(self.counselor.check_password("Nouveau-Mot-2027"))
        # La session reste valide après le changement de mot de passe.
        self.assertEqual(self.client.get(reverse("dossiers:dashboard")).status_code, 200)

    def test_student_pages_use_portal_layout(self):
        d = self.make_dossier()
        self.login(d.student)
        for url in [reverse("accounts:profile"), reverse("dossiers:notifications")]:
            resp = self.client.get(url)
            self.assertContains(resp, "portal-top")
            self.assertNotContains(resp, "Tableau de suivi")

    def test_legal_pages_are_public(self):
        for name in ["terms", "privacy"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)


class FinanceAndExportTests(BaseTestCase):
    def setUp(self):
        self.mine = self.make_dossier(email="mine@a.ml", counselor=self.counselor)
        self.other = self.make_dossier(email="other@a.ml", counselor=self.counselor2)
        for d in (self.mine, self.other):
            self.add_fee(d, 300000)
        services.record_payment(self.mine, self.counselor, amount=Decimal("100000"), method="orange_money")
        services.record_payment(self.other, self.counselor2, amount=Decimal("50000"), method="wave")

    def test_finances_totals_respect_scope(self):
        self.login(self.admin)
        resp = self.client.get(reverse("dossiers:finances"))
        self.assertEqual(resp.context["total"], 150000)
        self.assertEqual(resp.context["outstanding"], 450000)
        self.login(self.counselor)
        resp = self.client.get(reverse("dossiers:finances"))
        self.assertEqual(resp.context["total"], 100000)
        resp = self.client.get(reverse("dossiers:finances") + "?period=month&method=wave")
        self.assertEqual(resp.context["total"], 0)

    def test_payments_export_is_scoped_csv(self):
        self.login(self.counselor)
        resp = self.client.get(reverse("dossiers:payments_export"))
        self.assertEqual(resp["Content-Type"], "text/csv; charset=utf-8")
        body = resp.content.decode("utf-8-sig")
        self.assertIn("Orange Money", body)
        self.assertNotIn("Wave", body)

    def test_dossiers_export_and_csv_injection(self):
        self.mine.program = "=HYPERLINK(\"http://evil\")"
        self.mine.save()
        self.login(self.admin)
        body = self.client.get(reverse("dossiers:export")).content.decode("utf-8-sig")
        self.assertIn(self.mine.reference, body)
        self.assertIn(self.other.reference, body)
        self.assertIn("'=HYPERLINK", body)
        self.login(self.mine.student)
        self.assertEqual(self.client.get(reverse("dossiers:export")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dossiers:finances")).status_code, 403)
