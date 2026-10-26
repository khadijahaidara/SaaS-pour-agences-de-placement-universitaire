from datetime import date, timedelta
from decimal import Decimal

from django.urls import reverse
from django.utils import timezone

from agencies.models import Agency
from billing import services
from billing.models import Invoice, Plan, PlanChangeRequest, Subscription
from billing.tasks import renewal_notices
from core.exceptions import QuotaExceeded
from dossiers.tests.factories import BaseTestCase, User


class PlanTests(BaseTestCase):
    def set_plan(self, code, agency=None):
        agency = agency or self.agency
        sub = services.get_subscription(agency)
        sub.plan = Plan.objects.get(code=code)
        sub.save()
        agency._subscription_cache = None
        if hasattr(self.agency, "_subscription_cache"):
            del self.agency._subscription_cache

    def test_default_plans_and_trial_gets_pro(self):
        self.assertEqual(set(Plan.objects.values_list("code", flat=True)), {"starter", "pro", "business"})
        self.assertEqual(services.effective_plan(self.agency).code, "pro")
        self.assertTrue(services.has_feature(self.agency, "webhooks"))

    def test_dossier_quota_blocks_creation(self):
        plan = Plan.objects.get(code="starter")
        plan.max_active_dossiers = 1
        plan.save()
        self.set_plan("starter")
        self.make_dossier()
        agency = Agency.objects.get(pk=self.agency.pk)
        with self.assertRaises(QuotaExceeded):
            self.make_dossier(email="deux@a.ml", agency=agency)

    def test_staff_quota_on_invitation(self):
        plan = Plan.objects.get(code="starter")
        plan.max_staff = 3  # admin + 2 conseillers déjà présents
        plan.save()
        self.set_plan("starter")
        self.login(self.admin)
        resp = self.client.post(reverse("agencies:team"), {
            "first_name": "Nouveau", "last_name": "Membre", "email": "nouveau@a.ml", "phone": "",
            "access": "admin"})
        self.assertContains(resp, "Limite de 3 membres")
        self.assertFalse(User.objects.filter(email="nouveau@a.ml").exists())

    def test_invoice_paid_activates_agency(self):
        pro = Plan.objects.get(code="pro")
        invoice = services.issue_invoice(self.agency, plan=pro, cycle=Subscription.Cycle.YEARLY)
        self.assertRegex(invoice.number, r"^NM-\d{4}-\d{4}$")
        self.assertEqual(invoice.amount, pro.price_yearly)
        self.assertEqual(invoice.period_end, services.add_period(invoice.period_start, "yearly"))
        services.mark_paid(invoice, actor=None, method=Invoice.Method.ORANGE_MONEY, reference="OM123")
        agency = Agency.objects.get(pk=self.agency.pk)
        self.assertEqual(agency.plan, Agency.Plan.ACTIVE)
        self.assertEqual(agency.paid_until, invoice.period_end)
        self.assertEqual(Subscription.objects.get(agency=agency).cycle, "yearly")
        self.assertTrue(agency.audit_logs.filter(action="billing.invoice_paid").exists())

    def test_add_period_handles_month_ends(self):
        self.assertEqual(services.add_period(date(2027, 1, 31), "monthly"), date(2027, 2, 27))
        self.assertEqual(services.add_period(date(2027, 3, 1), "monthly"), date(2027, 3, 31))
        self.assertEqual(services.add_period(date(2027, 3, 1), "yearly"), date(2028, 2, 29))

    def test_request_change_and_console_flow(self):
        self.login(self.admin)
        resp = self.client.post(reverse("billing:request_change"), {"plan": "business", "cycle": "monthly"})
        self.assertRedirects(resp, reverse("billing:overview"), fetch_redirect_response=False)
        req = PlanChangeRequest.objects.get(agency=self.agency)
        console = User.objects.create_superuser(email="console@n.ml", password=self.password)
        self.login(console)
        self.client.post(reverse("console:invoice_create"), {"agency": self.agency.pk, "plan": req.plan_id,
                                                             "cycle": "monthly", "request": req.pk})
        invoice = Invoice.objects.get(agency=self.agency)
        self.client.post(reverse("console:invoice_paid", args=[invoice.pk]), {"method": "wave", "paid_on": ""})
        invoice.refresh_from_db()
        self.assertEqual(invoice.status, Invoice.Status.PAID)
        self.assertEqual(services.effective_plan(Agency.objects.get(pk=self.agency.pk)).code, "business")
        pdf = self.client.get(reverse("console:invoice_pdf", args=[invoice.pk]))
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

    def test_invoice_pdf_is_scoped_to_agency(self):
        invoice = services.issue_invoice(self.other_agency, plan=Plan.objects.get(code="pro"), cycle="monthly")
        self.login(self.admin)
        self.assertEqual(self.client.get(reverse("billing:invoice_pdf", args=[invoice.pk])).status_code, 404)

    def test_overview_requires_billing_permission(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("billing:overview")).status_code, 403)
        self.login(self.admin)
        resp = self.client.get(reverse("billing:overview"))
        self.assertContains(resp, "Choisir une formule")
        self.assertContains(resp, "Dossiers en cours")

    def test_renewal_task_issues_invoice_once(self):
        Agency.objects.filter(pk=self.agency.pk).update(plan=Agency.Plan.ACTIVE,
                                                        paid_until=timezone.localdate() + timedelta(days=5))
        self.assertEqual(renewal_notices()["factures_renouvellement"], 1)
        self.assertEqual(renewal_notices()["factures_renouvellement"], 0)
        invoice = Invoice.objects.get(agency=self.agency)
        self.assertEqual(invoice.period_start, timezone.localdate() + timedelta(days=6))

    def test_api_requires_feature(self):
        from api.models import ApiKey

        _, raw = ApiKey.generate(agency=self.agency, name="Site", created_by=self.admin)
        self.assertEqual(self.client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Api-Key {raw}").status_code, 200)
        self.set_plan("starter")
        self.assertEqual(self.client.get("/api/v1/me/", HTTP_AUTHORIZATION=f"Api-Key {raw}").status_code, 403)
