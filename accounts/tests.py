from decimal import Decimal

import pyotp
from django.core.cache import cache
from django.urls import reverse

from accounts.models import RecoveryCode, Role, TOTPDevice, UserSession
from accounts.rbac import ensure_default_roles
from audit.models import AuditLog
from dossiers import services
from dossiers.models import Payment
from dossiers.tests.factories import BaseTestCase, User


class RolesTests(BaseTestCase):
    def setUp(self):
        ensure_default_roles(self.agency)
        self.cashier = self.make_user("caisse@a.ml", User.Role.COUNSELOR, self.agency)
        self.cashier.agency_role = Role.objects.get(agency=self.agency, key="cashier")
        self.cashier.save()

    def test_cashier_sees_all_dossiers_but_not_admin_pages(self):
        d = self.make_dossier(counselor=self.counselor)
        self.login(self.cashier)
        self.assertEqual(self.client.get(reverse("dossiers:detail", args=[d.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dossiers:finances")).status_code, 200)
        self.assertEqual(self.client.get(reverse("agencies:team")).status_code, 403)
        self.assertEqual(self.client.get(reverse("agencies:settings")).status_code, 403)
        self.assertEqual(self.client.get(reverse("dossiers:create")).status_code, 403)

    def test_cashier_records_payment_but_cannot_review_documents(self):
        d = self.make_dossier()
        self.add_fee(d)
        self.login(self.cashier)
        self.client.post(reverse("dossiers:record_payment", args=[d.pk]),
                         {"amount": "100000", "method": "cash", "reference": "", "paid_on": ""})
        self.assertEqual(Payment.objects.filter(dossier=d).count(), 1)
        doc = d.document_requests.first()
        resp = self.client.post(reverse("dossiers:review_document", args=[d.pk, doc.pk]), {"decision": "approve"})
        self.assertEqual(resp.status_code, 403)

    def test_cancel_payment_needs_permission(self):
        d = self.make_dossier()
        self.add_fee(d)
        p = services.record_payment(d, self.admin, amount=Decimal(1000), method="cash")
        with self.assertRaises(services.BusinessRuleError):
            services.cancel_payment(p, self.counselor, "erreur")
        role = Role.objects.get(agency=self.agency, key="counselor")
        role.permissions = role.permissions + ["payments.cancel"]
        role.save()
        counselor = User.objects.get(pk=self.counselor.pk)
        counselor.agency_role = role
        counselor.save()
        services.cancel_payment(p, counselor, "erreur de saisie")
        self.assertTrue(Payment.objects.get(pk=p.pk).is_cancelled)

    def test_admin_changes_member_role_and_it_is_audited(self):
        self.login(self.admin)
        supervisor = Role.objects.get(agency=self.agency, key="supervisor")
        self.client.post(reverse("agencies:member_role", args=[self.counselor.pk]), {"access": f"role:{supervisor.pk}"})
        self.assertEqual(User.objects.get(pk=self.counselor.pk).agency_role, supervisor)
        self.assertTrue(AuditLog.objects.filter(agency=self.agency, action="team.role_changed").exists())

    def test_last_admin_cannot_be_demoted(self):
        other_admin = self.make_user("admin2@a.ml", User.Role.AGENCY_ADMIN, self.agency)
        self.login(other_admin)
        role = Role.objects.get(agency=self.agency, key="counselor")
        self.client.post(reverse("agencies:member_role", args=[self.admin.pk]), {"access": f"role:{role.pk}"})
        self.assertEqual(User.objects.get(pk=self.admin.pk).role, User.Role.COUNSELOR)
        self.login(self.admin)  # désormais conseiller : plus de droit d'équipe
        self.assertEqual(self.client.get(reverse("agencies:team")).status_code, 403)

    def test_no_privilege_escalation_through_roles(self):
        manager = Role.objects.create(agency=self.agency, name="RH", permissions=["team.manage", "roles.manage"])
        self.counselor.agency_role = manager
        self.counselor.save()
        self.login(self.counselor)
        resp = self.client.post(reverse("agencies:role_create"), {
            "name": "Tout", "description": "", "permissions": ["billing.manage", "team.manage"]})
        self.assertContains(resp, "accorder des permissions")
        self.assertFalse(Role.objects.filter(name="Tout").exists())

    def test_custom_roles_need_pro_plan(self):
        from billing.models import Plan
        from billing.services import get_subscription

        sub = get_subscription(self.agency)
        sub.plan = Plan.objects.get(code="starter")
        sub.save()
        self.login(self.admin)
        self.client.post(reverse("agencies:role_create"), {"name": "Stagiaire", "permissions": ["dossiers.edit"]})
        self.assertFalse(Role.objects.filter(name="Stagiaire").exists())


class TwoFactorTests(BaseTestCase):
    def setUp(self):
        cache.clear()

    def enable_2fa(self, user):
        device = TOTPDevice.objects.create(user=user, secret=pyotp.random_base32())
        self.login(user)
        self.client.post(reverse("accounts:totp_confirm"), {"code": device.totp().now()})
        self.client.logout()
        device.refresh_from_db()
        device.last_used_step = 0
        device.save()
        return device

    def test_setup_flow_generates_recovery_codes(self):
        self.login(self.admin)
        self.client.post(reverse("accounts:totp_start"))
        device = TOTPDevice.objects.get(user=self.admin)
        page = self.client.get(reverse("accounts:security"))
        self.assertContains(page, "<svg")
        self.client.post(reverse("accounts:totp_confirm"), {"code": device.totp().now()})
        self.assertTrue(User.objects.get(pk=self.admin.pk).has_2fa)
        self.assertEqual(RecoveryCode.objects.filter(user=self.admin).count(), 10)
        self.assertContains(self.client.get(reverse("accounts:security")), "codes de secours")

    def test_login_requires_second_factor(self):
        device = self.enable_2fa(self.admin)
        resp = self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": self.password})
        self.assertRedirects(resp, reverse("accounts:login_2fa"), fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)
        resp = self.client.post(reverse("accounts:login_2fa"), {"code": "000000"})
        self.assertContains(resp, "Code incorrect")
        resp = self.client.post(reverse("accounts:login_2fa"), {"code": device.totp().now()})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.admin.pk)

    def test_recovery_code_works_once(self):
        self.login(self.admin)
        self.client.post(reverse("accounts:totp_start"))
        device = TOTPDevice.objects.get(user=self.admin)
        self.client.post(reverse("accounts:totp_confirm"), {"code": device.totp().now()})
        codes = RecoveryCode.regenerate(self.admin)
        self.client.logout()
        for expected_ok in (True, False):
            self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": self.password})
            self.client.post(reverse("accounts:login_2fa"), {"code": codes[0]})
            self.assertEqual("_auth_user_id" in self.client.session, expected_ok)
            self.client.logout()

    def test_agency_can_enforce_2fa(self):
        self.agency.require_2fa = True
        self.agency.save()
        self.login(self.counselor)
        resp = self.client.get(reverse("dossiers:dashboard"))
        self.assertRedirects(resp, reverse("accounts:security") + "?obligatoire=1", fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("accounts:security")).status_code, 200)

    def test_policy_requires_admin_own_2fa_first(self):
        self.login(self.admin)
        self.client.post(reverse("agencies:security"), {"require_2fa": "on"})
        self.agency.refresh_from_db()
        self.assertFalse(self.agency.require_2fa)


class LoginProtectionTests(BaseTestCase):
    def setUp(self):
        cache.clear()

    def test_lockout_after_repeated_failures(self):
        for _ in range(5):
            self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": "mauvais"})
        resp = self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": self.password})
        self.assertContains(resp, "Trop de tentatives")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(AuditLog.objects.filter(action="auth.login_failed", agency=self.agency).count(), 5)
        self.assertTrue(AuditLog.objects.filter(action="auth.locked").exists())

    def test_login_creates_session_and_audit(self):
        self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": self.password})
        self.assertTrue(UserSession.objects.filter(user=self.admin).exists())
        self.assertTrue(AuditLog.objects.filter(action="auth.login", actor=self.admin).exists())

    def test_revoke_other_session(self):
        from django.test import Client

        other = Client()
        other.post(reverse("accounts:login"), {"username": self.admin.email, "password": self.password})
        self.client.post(reverse("accounts:login"), {"username": self.admin.email, "password": self.password})
        self.assertEqual(UserSession.objects.filter(user=self.admin).count(), 2)
        self.client.post(reverse("accounts:sessions_revoke_others"))
        self.assertEqual(UserSession.objects.filter(user=self.admin).count(), 1)
        self.assertEqual(other.get(reverse("dossiers:dashboard")).status_code, 302)  # renvoyé vers la connexion
