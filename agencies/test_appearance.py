import io

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from agencies.models import AgencyTheme
from agencies.theming import contrast, palette, theme_css, usable_brand
from billing.models import Plan
from billing.services import get_subscription
from dossiers.tests.factories import BaseTestCase, User


def jpeg(w=1600, h=900):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), "#336699").save(buf, "PNG")
    return SimpleUploadedFile("photo.png", buf.getvalue(), content_type="image/png")


BASE = {"c-brand_color": "#0F766E", "a-accent_color": "#E3A008", "a-sidebar_style": "brand", "a-font": "modern",
        "a-corners": "round", "a-login_style": "map", "a-branded_emails": "on", "a-portal_show_counselor": "on"}


class ThemingTests(BaseTestCase):
    def test_palette_keeps_text_readable(self):
        self.assertGreaterEqual(contrast(usable_brand("#FFE066"), "#ffffff"), 4.5)
        self.agency.brand_color = "#FFE066"
        pal = palette(self.agency)
        self.assertGreaterEqual(contrast(pal["--river"], pal["--on-river"]), 4.5)

    def test_appearance_saved_and_applied(self):
        self.login(self.admin)
        resp = self.client.post(reverse("agencies:appearance"), {**BASE, "a-link_label_0": "Campus France",
                                                                 "a-link_url_0": "https://www.campusfrance.org"})
        self.assertRedirects(resp, reverse("agencies:appearance"), fetch_redirect_response=False)
        theme = AgencyTheme.objects.get(agency=self.agency)
        self.assertEqual(theme.portal_links, [{"label": "Campus France", "url": "https://www.campusfrance.org"}])
        page = self.client.get(reverse("dossiers:dashboard"))
        self.assertIn("--river:#0f766e", page.content.decode().lower())
        self.assertContains(page, "sidebar-brand")
        self.assertIn('"Manrope", system-ui, sans-serif', theme_css(self.agency.__class__.objects.get(pk=self.agency.pk)))

    def test_images_are_reencoded_and_public(self):
        self.login(self.admin)
        self.client.post(reverse("agencies:appearance"), {**BASE, "a-login_style": "image", "a-login_image": jpeg()})
        theme = AgencyTheme.objects.get(agency=self.agency)
        self.assertTrue(theme.login_image.name.endswith(".jpg"))
        self.client.logout()
        from django.core.signals import request_finished
        from django.db import close_old_connections

        request_finished.disconnect(close_old_connections)
        try:
            resp = self.client.get(reverse("agency_asset", args=[self.agency.slug, "connexion"]))
            self.assertEqual(resp["Content-Type"], "image/jpeg")
            resp.close()
        finally:
            request_finished.connect(close_old_connections)
        login = self.client.get(reverse("accounts:login") + f"?agence={self.agency.slug}")
        self.assertContains(login, "login-image")

    def test_image_style_requires_photo_and_rejects_fake_images(self):
        self.login(self.admin)
        resp = self.client.post(reverse("agencies:appearance"), {**BASE, "a-login_style": "image"})
        self.assertContains(resp, "Ajoutez une photo")
        fake = SimpleUploadedFile("x.jpg", b"pas une image", content_type="image/jpeg")
        resp = self.client.post(reverse("agencies:appearance"), {**BASE, "a-portal_cover": fake})
        self.assertContains(resp, "image valide")

    def test_white_label_requires_business(self):
        self.login(self.admin)
        self.client.post(reverse("agencies:appearance"), {**BASE, "a-hide_platform_branding": "on"})
        self.assertFalse(AgencyTheme.objects.get(agency=self.agency).hide_platform_branding)
        sub = get_subscription(self.agency)
        sub.plan = Plan.objects.get(code="business")
        sub.save()
        self.client.post(reverse("agencies:appearance"), {**BASE, "a-hide_platform_branding": "on"})
        self.assertTrue(AgencyTheme.objects.get(agency=self.agency).hide_platform_branding)
        page = self.client.get(reverse("dossiers:dashboard"))
        self.assertNotContains(page, "Propulsé par NEURALIS")
        self.assertContains(page, f"· {self.agency.name}</title>")

    def test_counselor_cannot_change_appearance(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("agencies:appearance")).status_code, 403)

    def test_branded_email(self):
        AgencyTheme.objects.create(agency=self.agency, email_signature="L'équipe A")
        with self.captureOnCommitCallbacks(execute=True):
            self.make_dossier(counselor=self.counselor2)
        msg = mail.outbox[-1]
        self.assertTrue(msg.subject.startswith(f"[{self.agency.name}]"))
        html = msg.alternatives[0][0]
        self.assertIn("L&#x27;équipe A", html)
        self.assertIn("Envoyé avec NEURALIS Mobility", html)


class PreferencesTests(BaseTestCase):
    def test_dark_mode_and_density(self):
        self.login(self.counselor)
        self.client.post(reverse("accounts:profile"), {"save_display": "1", "d-ui_theme": "dark", "d-ui_density": "compact"})
        page = self.client.get(reverse("dossiers:dashboard"))
        self.assertContains(page, 'data-theme="dark" data-density="compact"')
        self.client.post(reverse("accounts:set_theme"), {"theme": "light", "next": "/agence/"})
        self.assertEqual(User.objects.get(pk=self.counselor.pk).ui_theme, "light")

    def test_dashboard_layout(self):
        self.make_dossier()
        self.login(self.admin)
        self.client.post(reverse("accounts:dashboard_layout"), {"widgets": ["deadlines", "payments", "team", "bidon"]})
        self.assertEqual(User.objects.get(pk=self.admin.pk).dashboard_layout, ["deadlines", "payments", "team"])
        page = self.client.get(reverse("dossiers:dashboard"))
        self.assertContains(page, 'data-widget="deadlines"')
        self.assertContains(page, "Charge de l&#x27;équipe")
        self.assertNotContains(page, 'data-widget="priority"')
        # Un conseiller ne peut pas afficher les blocs réservés
        self.login(self.counselor)
        self.client.post(reverse("accounts:dashboard_layout"), {"widgets": ["team", "activity"]})
        self.assertEqual(User.objects.get(pk=self.counselor.pk).dashboard_layout, ["activity"])
        self.client.post(reverse("accounts:dashboard_layout"), {"reset": "1"})
        self.assertContains(self.client.get(reverse("dossiers:dashboard")), 'data-widget="priority"')
