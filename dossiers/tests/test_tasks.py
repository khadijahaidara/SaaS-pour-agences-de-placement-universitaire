from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from console.models import TaskRun
from dossiers import tasks
from dossiers.models import Notification, ServiceFee

from .factories import BaseTestCase


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ScheduledTaskTests(BaseTestCase):
    def test_document_reminders_are_not_repeated(self):
        d = self.make_dossier()
        doc = d.document_requests.first()
        doc.due_date = timezone.localdate() + timedelta(days=1)
        doc.save()
        self.assertEqual(tasks.remind_documents()["pieces"], 1)
        self.assertTrue(Notification.objects.filter(recipient=d.student, message__startswith="Rappel").exists())
        self.assertEqual(tasks.remind_documents()["pieces"], 0)  # pas de doublon
        later = timezone.now() + timedelta(days=4)
        self.assertEqual(tasks.remind_documents(now=later)["pieces"], 1)

    def test_payment_reminder_only_when_amount_due_is_not_covered(self):
        d = self.make_dossier()
        ServiceFee.objects.create(dossier=d, label="Acompte", amount=Decimal("100000"),
                                  due_date=timezone.localdate() - timedelta(days=1))
        self.assertEqual(tasks.remind_payments()["rappels"], 1)
        self.assertEqual(tasks.remind_payments()["rappels"], 0)
        d2 = self.make_dossier(email="d2@a.ml")
        ServiceFee.objects.create(dossier=d2, label="Acompte", amount=Decimal("1000"),
                                  due_date=timezone.localdate())
        from dossiers import services

        services.record_payment(d2, self.counselor, amount=Decimal("1000"), method="cash")
        self.assertEqual(tasks.remind_payments()["rappels"], 0)

    def test_trial_notices_once(self):
        self.agency.trial_ends_at = timezone.now() + timedelta(days=2)
        self.agency.save()
        self.assertEqual(tasks.trial_notices()["avertis"], 1)
        self.assertEqual(tasks.trial_notices()["avertis"], 0)
        self.agency.trial_ends_at = timezone.now() - timedelta(hours=1)
        self.agency.save()
        self.assertEqual(tasks.trial_notices()["termines"], 1)
        self.assertTrue(Notification.objects.filter(recipient=self.admin, message__contains="terminé").exists())

    def test_digest_once_a_day_and_respects_preference(self):
        d = self.make_dossier()
        d.status = "blocked"
        d.blocked_reason = "Attente"
        d.save()
        self.counselor2.daily_digest = False
        self.counselor2.save()
        out = StringIO()
        call_command("run_scheduled_tasks", stdout=out)
        digests = [m for m in mail.outbox if "à traiter" in m.subject]
        self.assertEqual({m.to[0] for m in digests}, {"admin@a.ml", "conseiller@a.ml"})
        call_command("run_scheduled_tasks", stdout=out)
        self.assertEqual(len([m for m in mail.outbox if "à traiter" in m.subject]), 2)
        self.assertTrue(TaskRun.objects.filter(name="resume_quotidien", status="success").exists())
        self.assertIn("déjà exécutée", out.getvalue())

    def test_email_preference_disables_emails_not_notifications(self):
        d = self.make_dossier()
        d.student.notify_email = False
        d.student.save()
        mail.outbox.clear()
        from dossiers import services

        with self.captureOnCommitCallbacks(execute=True):
            services.request_document(d, self.counselor, name="Visa")
        self.assertFalse([m for m in mail.outbox if d.student.email in m.to])
        self.assertTrue(Notification.objects.filter(recipient=d.student, message__contains="Visa").exists())
