from django.urls import reverse

from dossiers import services
from dossiers.models import DocumentFile, DocumentRequest, Dossier

from .factories import PNG_BYTES, BaseTestCase, pdf


class IsolationTests(BaseTestCase):
    """Aucun utilisateur ne doit voir un dossier hors de son périmètre."""

    def setUp(self):
        self.d = self.make_dossier(counselor=self.counselor)
        self.other = self.make_dossier(email="etu2@a.ml", counselor=self.counselor2)
        self.foreign = self.make_dossier(email="etu@b.ml", agency=self.other_agency, counselor=self.other_admin,
                                         workflow=self.other_agency.workflow_templates.first(), actor=self.other_admin)

    def test_other_agency_gets_404(self):
        self.login(self.other_admin)
        self.assertEqual(self.client.get(reverse("dossiers:detail", args=[self.d.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("dossiers:detail", args=[self.foreign.pk])).status_code, 200)

    def test_counselor_sees_only_assigned(self):
        self.login(self.counselor)
        self.assertEqual(self.client.get(reverse("dossiers:detail", args=[self.d.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("dossiers:detail", args=[self.other.pk])).status_code, 404)
        resp = self.client.get(reverse("dossiers:list"))
        self.assertContains(resp, self.d.reference)
        self.assertNotContains(resp, self.other.reference)

    def test_admin_sees_whole_agency_only(self):
        self.login(self.admin)
        resp = self.client.get(reverse("dossiers:list"))
        self.assertContains(resp, self.d.reference)
        self.assertContains(resp, self.other.reference)
        self.assertNotContains(resp, self.foreign.reference)

    def test_student_cannot_access_agency_space_or_other_dossier(self):
        self.login(self.d.student)
        self.assertEqual(self.client.get(reverse("dossiers:dashboard")).status_code, 403)
        self.assertEqual(self.client.get(reverse("portal:dossier", args=[self.other.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("portal:dossier", args=[self.d.pk])).status_code, 200)

    def test_document_download_is_protected(self):
        doc = self.other.document_requests.first()
        services.submit_document(doc, self.other.student, pdf())
        f = DocumentFile.objects.get(request=doc)
        url = reverse("dossiers:document_download", args=[f.pk])
        self.assertEqual(self.client.get(url).status_code, 302)  # anonyme → connexion
        self.login(self.d.student)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login(self.counselor)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login(self.other.student)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Cache-Control"], "private, no-store")

    def test_internal_events_hidden_from_student(self):
        services.assign_counselor(self.d, self.admin, self.counselor2)
        self.login(self.d.student)
        resp = self.client.get(reverse("portal:dossier", args=[self.d.pk]))
        self.assertNotContains(resp, "Conseiller responsable")

    def test_counselor_cannot_reassign_or_manage_team(self):
        self.login(self.counselor)
        self.client.post(reverse("dossiers:assign", args=[self.d.pk]), {"counselor": self.counselor2.pk})
        self.d.refresh_from_db()
        self.assertEqual(self.d.counselor, self.counselor)
        self.assertEqual(self.client.get(reverse("agencies:team")).status_code, 403)


class PriorityJourneyViewTests(BaseTestCase):
    def test_journey_through_http(self):
        self.login(self.counselor)
        resp = self.client.post(reverse("dossiers:create"), {
            "student_first_name": "Seydou", "student_last_name": "Bagayoko", "student_email": "seydou@a.ml",
            "student_phone": "+22370000000", "workflow": self.workflow.pk, "destination_country": "",
        })
        dossier = Dossier.objects.get(student__email="seydou@a.ml")
        self.assertRedirects(resp, reverse("dossiers:detail", args=[dossier.pk]), fetch_redirect_response=False)
        self.assertEqual(dossier.counselor, self.counselor)  # un conseiller suit ses propres créations
        detail = self.client.get(resp.url)
        self.assertContains(detail, "/compte/activation/")  # lien d'invitation affiché

        # Demande d'une pièce supplémentaire
        self.client.post(reverse("dossiers:request_document", args=[dossier.pk]),
                         {"name": "Certificat médical", "is_required": "on"})
        doc = dossier.document_requests.get(name="Certificat médical")

        # L'étudiant active son compte puis dépose depuis le portail
        student = dossier.student
        student.set_password(self.password)
        student.save()
        self.login(student)
        portal = self.client.get(reverse("portal:dossier", args=[dossier.pk]))
        self.assertContains(portal, "Votre prochaine action")
        resp = self.client.post(reverse("portal:upload", args=[dossier.pk, doc.pk]),
                                {"file": pdf("certificat.pdf")})
        self.assertRedirects(resp, reverse("portal:dossier", args=[dossier.pk]))
        doc.refresh_from_db()
        self.assertEqual(doc.status, DocumentRequest.Status.SUBMITTED)

        # Le conseiller retourne la pièce avec un motif, l'étudiant le voit
        self.login(self.counselor)
        self.client.post(reverse("dossiers:review_document", args=[dossier.pk, doc.pk]),
                         {"decision": "reject", "reason": "Date manquante"})
        self.login(student)
        portal = self.client.get(reverse("portal:dossier", args=[dossier.pk]))
        self.assertContains(portal, "Date manquante")
        self.assertContains(portal, "Déposer à nouveau : Certificat médical")

    def test_dashboard_lists_dossier_needing_review(self):
        d = self.make_dossier()
        services.submit_document(d.document_requests.first(), d.student, pdf())
        self.login(self.counselor)
        resp = self.client.get(reverse("dossiers:dashboard"))
        self.assertContains(resp, "pièce(s) à vérifier")
        self.assertContains(resp, d.reference)


class UploadValidationTests(BaseTestCase):
    def setUp(self):
        self.d = self.make_dossier()
        self.doc = self.d.document_requests.first()
        self.login(self.d.student)
        self.url = reverse("portal:upload", args=[self.d.pk, self.doc.pk])

    def _post(self, upload):
        self.client.post(self.url, {"file": upload})
        self.doc.refresh_from_db()
        return self.doc.status

    def test_rejects_wrong_extension(self):
        self.assertEqual(self._post(pdf("virus.exe")), DocumentRequest.Status.REQUESTED)

    def test_rejects_spoofed_content(self):
        self.assertEqual(self._post(pdf("faux.pdf", b"MZ\x90\x00 not a pdf")), DocumentRequest.Status.REQUESTED)

    def test_accepts_png_photo(self):
        self.assertEqual(self._post(pdf("photo.png", PNG_BYTES)), DocumentRequest.Status.SUBMITTED)

    def test_rejects_too_large(self):
        with self.settings(MAX_UPLOAD_SIZE=10):
            self.assertEqual(self._post(pdf()), DocumentRequest.Status.REQUESTED)


class InvitationTests(BaseTestCase):
    def test_student_activates_account_via_link(self):
        d, created = services.create_dossier(agency=self.agency, actor=self.admin, student_email="new@a.ml",
                                             student_first_name="Nana", student_last_name="Sow", workflow=self.workflow)
        self.assertTrue(created)
        self.assertFalse(d.student.has_usable_password())
        path = services.build_invitation_path(d.student)
        resp = self.client.get(path, follow=True)
        self.assertContains(resp, "Choisissez votre mot de passe")
        resp = self.client.post(resp.redirect_chain[-1][0], {"new_password1": "Bamako-2027!", "new_password2": "Bamako-2027!"}, follow=True)
        d.student.refresh_from_db()
        self.assertTrue(d.student.check_password("Bamako-2027!"))
        # Déjà connecté : la page d'accueil mène au portail
        self.assertRedirects(self.client.get("/"), reverse("portal:home"), target_status_code=302)
