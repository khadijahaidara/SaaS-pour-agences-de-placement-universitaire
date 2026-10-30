import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.signals import request_finished
from django.db import close_old_connections
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agencies.models import Agency
from agencies.services import create_agency
from console.importer import import_prospects
from console.models import Prospect, ProspectActivity
from dossiers import services
from dossiers.models import Dossier

User = get_user_model()
PWD = "Motdepasse-Test-42"

CSV = (
    "Prospect;Zone;Téléphone;E-mail;Segment;Site Web;WhatsApp;Décideur / fonction;Canal recommandé;Source vérification;Priorité Mobility\n"
    "Study Test Mali;ACI 2000;76 00 00 01;contact@studytest.ml;Placement universitaire;https://studytest.ml;À vérifier à partir du numéro public;Awa — CEO;WhatsApp;https://studytest.ml;P1 — cœur de cible\n"
    "Centre Test;Bamako;20 00 00 02;Non publié / à vérifier;Formation;Non trouvé lors de cette passe;;;Appel;annuaire;P3 — prospect à qualifier\n"
)


class SignupTests(TestCase):
    def setUp(self):
        cache.clear()

    def _data(self, **kw):
        data = {"agency_name": "Horizon Études", "city": "Bamako", "phone": "+223 70 11 22 33",
                "first_name": "Awa", "last_name": "Traoré", "email": "awa@horizon.ml",
                "password": "Bamako-Etudes-2027", "accept_terms": "on", "website": ""}
        data.update(kw)
        return data

    def test_self_signup_creates_trial_agency_and_logs_in(self):
        resp = self.client.post(reverse("signup"), self._data())
        self.assertRedirects(resp, reverse("dossiers:dashboard"))
        agency = Agency.objects.get(name="Horizon Études")
        self.assertEqual(agency.plan, Agency.Plan.TRIAL)
        self.assertTrue(agency.is_operational)
        self.assertEqual(agency.trial_days_left, 14)
        self.assertEqual(agency.workflow_templates.count(), 4)
        admin = User.objects.get(email="awa@horizon.ml")
        self.assertEqual(admin.role, User.Role.AGENCY_ADMIN)
        self.assertContains(self.client.get(reverse("dossiers:dashboard")), "Bien démarrer")

    def test_signup_links_matching_prospect(self):
        p = Prospect.objects.create(name="Horizon", email="awa@horizon.ml", priority="P1")
        self.client.post(reverse("signup"), self._data())
        p.refresh_from_db()
        self.assertEqual(p.status, Prospect.Status.TRIAL)
        self.assertIsNotNone(p.agency)

    def test_signup_rejects_duplicate_email_weak_password_honeypot_and_terms(self):
        User.objects.create_user(email="awa@horizon.ml", password=PWD, role=User.Role.PLATFORM_ADMIN)
        self.client.post(reverse("signup"), self._data())
        self.client.post(reverse("signup"), self._data(email="b@x.ml", password="12345678"))
        self.client.post(reverse("signup"), self._data(email="c@x.ml", website="http://spam"))
        self.client.post(reverse("signup"), self._data(email="d@x.ml", accept_terms=""))
        self.assertFalse(Agency.objects.exists())

    def test_signup_rate_limited_per_ip(self):
        for i in range(6):
            self.client.logout()
            self.client.post(reverse("signup"), self._data(email=f"u{i}@x.ml", agency_name=f"Agence {i}"))
        self.assertEqual(Agency.objects.count(), 5)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="placement-console-tests-"))
class SubscriptionTests(TestCase):
    def test_expired_trial_blocks_new_dossiers_but_keeps_read_access(self):
        agency, admin = create_agency(name="Agence Expirée", admin_email="a@exp.ml", admin_password=PWD)
        wf = agency.workflow_templates.first()
        d, _ = services.create_dossier(agency=agency, actor=admin, student_email="e@exp.ml",
                                       student_first_name="E", student_last_name="F", workflow=wf)
        agency.trial_ends_at = timezone.now() - timedelta(days=1)
        agency.save()
        self.assertFalse(agency.is_operational)
        with self.assertRaises(services.BusinessRuleError):
            services.create_dossier(agency=agency, actor=admin, student_email="g@exp.ml",
                                    student_first_name="G", student_last_name="H", workflow=wf)
        self.client.force_login(admin)
        self.assertRedirects(self.client.get(reverse("dossiers:create")), reverse("dossiers:list"))
        self.assertEqual(self.client.get(reverse("dossiers:detail", args=[d.pk])).status_code, 200)
        self.assertContains(self.client.get(reverse("dossiers:list")), "Essai terminé")

    def test_agency_settings_brand_color_and_logo(self):
        agency, admin = create_agency(name="Agence Couleur", admin_email="a@col.ml", admin_password=PWD)
        self.client.force_login(admin)
        import io

        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (8, 8), "#0f766e").save(buf, "PNG")
        png = buf.getvalue()
        resp = self.client.post(reverse("agencies:settings"), {
            "name": "Agence Couleur", "city": "Bamako", "currency": "FCFA",
            "logo": SimpleUploadedFile("logo.png", png, content_type="image/png"),
        })
        self.assertRedirects(resp, reverse("agencies:settings"))
        resp = self.client.post(reverse("agencies:appearance"), {
            "c-brand_color": "#123456", "a-accent_color": "#C98A2B", "a-sidebar_style": "brand", "a-font": "modern",
            "a-corners": "round", "a-login_style": "map", "a-branded_emails": "on", "a-portal_show_counselor": "on"})
        self.assertRedirects(resp, reverse("agencies:appearance"))
        agency.refresh_from_db()
        self.assertEqual(agency.brand_color, "#123456")
        logo_resp = self.client.get(reverse("agency_logo", args=[agency.slug]))
        self.assertEqual(logo_resp.status_code, 200)
        # Libère le fichier (indispensable sous Windows) sans fermer la connexion de test.
        request_finished.disconnect(close_old_connections)
        try:
            logo_resp.close()
        finally:
            request_finished.connect(close_old_connections)


class ConsoleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.staff = User.objects.create_superuser(email="console@neuralis.ml", password=PWD)
        cls.agency, cls.agency_admin = create_agency(name="Agence X", admin_email="x@x.ml", admin_password=PWD)

    def test_only_platform_admins_reach_console(self):
        self.client.force_login(self.agency_admin)
        self.assertEqual(self.client.get(reverse("console:dashboard")).status_code, 403)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("console:dashboard")).status_code, 200)
        self.assertRedirects(self.client.get("/"), reverse("console:dashboard"))

    def test_import_csv_is_idempotent_and_cleans_placeholders(self):
        r1 = import_prospects(CSV.encode(), "p.csv")
        r2 = import_prospects(CSV.encode(), "p.csv")
        self.assertEqual((r1["created"], r2["created"], r2["updated"]), (2, 0, 2))
        p = Prospect.objects.get(name="Study Test Mali")
        self.assertEqual(p.priority, "P1")
        self.assertEqual(p.whatsapp, "")
        self.assertEqual(p.whatsapp_number, "22376000001")
        self.assertEqual(Prospect.objects.get(name="Centre Test").email, "")

    def test_import_via_upload_and_pipeline(self):
        self.client.force_login(self.staff)
        resp = self.client.post(reverse("console:prospect_import"),
                                {"file": SimpleUploadedFile("p.csv", CSV.encode(), content_type="text/csv")})
        self.assertRedirects(resp, reverse("console:prospects"))
        p = Prospect.objects.get(name="Study Test Mali")
        # Un appel noté fait passer le prospect en « Contacté » et l'attribue.
        self.client.post(reverse("console:prospect_activity", args=[p.pk]),
                         {"kind": "call", "summary": "Intéressée, démo jeudi", "next_follow_up": "2030-01-01"})
        p.refresh_from_db()
        self.assertEqual(p.status, Prospect.Status.CONTACTED)
        self.assertEqual(p.owner, self.staff)
        self.client.post(reverse("console:prospect_status", args=[p.pk]), {"status": "lost", "reason": "Budget"})
        p.refresh_from_db()
        self.assertEqual((p.status, p.lost_reason, p.next_follow_up), ("lost", "Budget", None))
        self.assertEqual(p.activities.filter(kind=ProspectActivity.Kind.STATUS).count(), 1)
        self.assertContains(self.client.get(reverse("console:prospects") + "?priority=P1"), "Study Test Mali")

    def test_convert_prospect_into_trial_agency(self):
        self.client.force_login(self.staff)
        p = Prospect.objects.create(name="Agence Prospect", priority="P1", whatsapp="76 00 00 09")
        resp = self.client.post(reverse("console:prospect_convert", args=[p.pk]), {
            "agency_name": "Agence Prospect", "admin_email": "boss@prospect.ml", "admin_first_name": "Ba",
        })
        self.assertRedirects(resp, reverse("console:prospect_detail", args=[p.pk]), fetch_redirect_response=False)
        p.refresh_from_db()
        self.assertEqual(p.status, Prospect.Status.TRIAL)
        boss = User.objects.get(email="boss@prospect.ml")
        self.assertFalse(boss.has_usable_password())
        self.assertContains(self.client.get(resp.url), "/compte/activation/")

    def test_plan_actions(self):
        self.client.force_login(self.staff)
        url = reverse("console:agency_plan", args=[self.agency.pk])
        self.client.post(url, {"action": "activate_year"})
        self.agency.refresh_from_db()
        self.assertEqual(self.agency.plan, Agency.Plan.ACTIVE)
        self.assertGreater(self.agency.paid_until, timezone.localdate() + timedelta(days=360))
        self.client.post(url, {"action": "suspend"})
        self.agency.refresh_from_db()
        self.assertFalse(self.agency.is_operational)
        self.client.post(url, {"action": "reactivate"})
        self.agency.refresh_from_db()
        self.assertTrue(self.agency.is_operational)

    def test_agency_pages_render(self):
        self.client.force_login(self.agency_admin)
        for name in ["dossiers:dashboard", "dossiers:list", "dossiers:create", "agencies:settings",
                     "agencies:team", "agencies:workflows", "dossiers:notifications"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.client.force_login(self.staff)
        for name in ["console:dashboard", "console:prospects", "console:agencies", "console:prospect_create",
                     "console:prospect_import"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
