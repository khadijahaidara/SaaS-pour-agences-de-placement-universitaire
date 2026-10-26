from decimal import Decimal

from dossiers import services
from dossiers.models import DocumentRequest, Dossier, DossierStage, Notification
from dossiers.services import BusinessRuleError

from .factories import BaseTestCase, pdf


class CreateDossierTests(BaseTestCase):
    def test_creates_student_stages_and_checklist_from_template(self):
        d = self.make_dossier()
        self.assertEqual(d.student.role, "student")
        self.assertEqual(d.student.agency, self.agency)
        self.assertEqual(d.destination_country, "Maroc")
        self.assertEqual(d.stages.count(), self.workflow.stages.count())
        self.assertEqual(d.document_requests.count(), self.workflow.documents.count())
        first = d.stages.order_by("order").first()
        self.assertEqual(first.status, DossierStage.Status.IN_PROGRESS)
        self.assertIsNotNone(first.due_date)
        self.assertTrue(d.reference.startswith("DOS-"))

    def test_rejects_email_of_user_from_another_agency(self):
        with self.assertRaises(BusinessRuleError):
            services.create_dossier(agency=self.agency, actor=self.admin, student_email="admin@b.ml",
                                    student_first_name="X", student_last_name="Y", workflow=self.workflow)

    def test_rejects_template_of_another_agency(self):
        foreign = self.other_agency.workflow_templates.first()
        with self.assertRaises(BusinessRuleError):
            services.create_dossier(agency=self.agency, actor=self.admin, student_email="n@a.ml",
                                    student_first_name="X", student_last_name="Y", workflow=foreign)


class PriorityJourneyTests(BaseTestCase):
    """Parcours du cahier des charges : demande → dépôt → validation/retour → progression."""

    def test_full_priority_journey(self):
        d = self.make_dossier()
        student = d.student
        stage1 = d.current_stage
        docs = list(stage1.document_requests.all())
        self.assertTrue(docs)

        # Impossible d'avancer tant que les pièces obligatoires ne sont pas validées.
        with self.assertRaisesMessage(BusinessRuleError, "pièces obligatoires"):
            services.advance_stage(d, self.counselor)

        # L'étudiant dépose, le conseiller est notifié.
        services.submit_document(docs[0], student, pdf())
        docs[0].refresh_from_db()
        self.assertEqual(docs[0].status, DocumentRequest.Status.SUBMITTED)
        self.assertTrue(Notification.objects.filter(recipient=self.counselor, dossier=d).exists())

        # Retour avec motif obligatoire.
        with self.assertRaises(BusinessRuleError):
            services.review_document(docs[0], self.counselor, approve=False, reason=" ")
        services.review_document(docs[0], self.counselor, approve=False, reason="Illisible")
        docs[0].refresh_from_db()
        self.assertEqual(docs[0].status, DocumentRequest.Status.REJECTED)
        self.assertEqual(d.next_action_for_student()["label"], f"Déposer à nouveau : {docs[0].name}")

        # Nouveau dépôt puis validation de toutes les pièces de l'étape.
        for doc in docs:
            services.submit_document(doc, student, pdf())
            services.review_document(doc, self.counselor, approve=True)

        nxt = services.advance_stage(d, self.counselor)
        stage1.refresh_from_db()
        self.assertEqual(stage1.status, DossierStage.Status.DONE)
        self.assertEqual(nxt.status, DossierStage.Status.IN_PROGRESS)
        self.assertEqual(d.current_stage, nxt)
        self.assertTrue(Notification.objects.filter(recipient=student, message__contains=nxt.name).exists())
        self.assertIn(nxt.name, d.next_action_for_student()["label"])

    def test_last_stage_completes_dossier(self):
        d = self.make_dossier()
        for doc in d.document_requests.all():
            services.submit_document(doc, d.student, pdf())
            services.review_document(doc, self.counselor, approve=True)
        while d.current_stage:
            services.advance_stage(d, self.counselor)
        d.refresh_from_db()
        self.assertEqual(d.status, Dossier.Status.COMPLETED)
        self.assertEqual(d.progress_percent(), 100)
        with self.assertRaises(BusinessRuleError):
            services.request_document(d, self.counselor, name="Autre")

    def test_only_agency_admin_can_force(self):
        d = self.make_dossier()
        with self.assertRaises(BusinessRuleError):
            services.advance_stage(d, self.counselor, force=True)
        services.advance_stage(d, self.admin, force=True)
        self.assertTrue(d.events.filter(message__startswith="Passage forcé", visible_to_student=False).exists())

    def test_blocked_dossier_cannot_progress_and_needs_reason(self):
        d = self.make_dossier()
        with self.assertRaises(BusinessRuleError):
            services.set_status(d, self.counselor, Dossier.Status.BLOCKED, "")
        services.set_status(d, self.counselor, Dossier.Status.BLOCKED, "Attente équivalence")
        with self.assertRaisesMessage(BusinessRuleError, "Débloquez"):
            services.advance_stage(d, self.admin, force=True)
        self.assertEqual(d.alerts()[0]["code"], "blocked")


class PaymentTests(BaseTestCase):
    def test_balance_and_overpayment(self):
        d = self.make_dossier()
        self.add_fee(d, 500000)
        services.record_payment(d, self.counselor, amount=Decimal("200000"), method="orange_money")
        self.assertEqual(d.balance(), Decimal("300000"))
        with self.assertRaises(BusinessRuleError):
            services.record_payment(d, self.counselor, amount=Decimal("300001"), method="cash")

    def test_cancel_payment_restores_balance_admin_only(self):
        d = self.make_dossier()
        self.add_fee(d, 100000)
        p = services.record_payment(d, self.counselor, amount=Decimal("100000"), method="cash")
        self.assertEqual(d.balance(), 0)
        with self.assertRaises(BusinessRuleError):
            services.cancel_payment(p, self.counselor, "erreur")
        services.cancel_payment(p, self.admin, "Erreur de saisie")
        self.assertEqual(d.balance(), Decimal("100000"))
        self.assertRegex(p.receipt_number, r"^AA-\d{4}-\d{4}$")

    def test_next_action_asks_payment_when_documents_ok(self):
        d = self.make_dossier()
        self.add_fee(d, 1000)
        for doc in d.document_requests.all():
            services.submit_document(doc, d.student, pdf())
            services.review_document(doc, self.counselor, approve=True)
        self.assertEqual(d.next_action_for_student()["kind"], "payment")


class AlertTests(BaseTestCase):
    def test_overdue_stage_and_review_raise_priority(self):
        from datetime import timedelta

        from django.utils import timezone

        d = self.make_dossier()
        base = d.priority_score()
        stage = d.current_stage
        stage.due_date = timezone.localdate() - timedelta(days=5)
        stage.save()
        services.submit_document(d.document_requests.first(), d.student, pdf())
        codes = {a["code"] for a in d.alerts()}
        self.assertIn("stage_overdue", codes)
        self.assertIn("to_review", codes)
        self.assertGreater(d.priority_score(), base)
