"""Données de démonstration pour présenter le parcours prioritaire.

Usage : python manage.py seed_demo   (mot de passe de tous les comptes : demo12345)
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test.utils import override_settings
from django.utils import timezone

from agencies.models import Agency
from dossiers import services
from dossiers.defaults import install_default_workflows
from dossiers.models import DocumentRequest, Dossier, WorkflowTemplate

User = get_user_model()
PASSWORD = "demo12345"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class Command(BaseCommand):
    help = "Crée une agence de démonstration avec des dossiers à différents stades."

    def handle(self, *args, **opts):
        # Pas de courriels réels pendant la création des données de démonstration.
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.dummy.EmailBackend"):
            self._seed()

    @transaction.atomic
    def _seed(self):
        if Agency.objects.filter(slug="agence-demo-bamako").exists():
            if not User.objects.filter(email="console@demo.ml").exists():
                User.objects.create_superuser(email="console@demo.ml", password=PASSWORD, first_name="Équipe",
                                              last_name="NEURALIS")
                self.stdout.write("Compte console NEURALIS ajouté : console@demo.ml")
            self.stdout.write("Les données de démonstration existent déjà.")
            return
        from agencies.services import create_agency
        from console.models import Prospect

        agency, admin = create_agency(
            name="Agence Démo Bamako", admin_email="admin@demo.ml", admin_password=PASSWORD,
            admin_first_name="Khadija", admin_last_name="Traoré", phone="+223 20 00 00 00", source="demo",
        )
        agency.slug = "agence-demo-bamako"
        agency.address = "ACI 2000, Bamako"
        agency.brand_color = "#9C3F1C"
        agency.welcome_message = "Bienvenue ! Suivez ici chaque étape de votre départ. Votre conseiller reste joignable sur WhatsApp."
        agency.save()

        def mk(email, first, last, role, phone=""):
            return User.objects.create_user(email=email, password=PASSWORD, first_name=first, last_name=last,
                                            role=role, agency=agency, phone=phone)

        if not User.objects.filter(email="console@demo.ml").exists():
            User.objects.create_superuser(email="console@demo.ml", password=PASSWORD, first_name="Équipe",
                                          last_name="NEURALIS")
        if not Prospect.objects.exists():
            for name, prio, status in [("Agence Exemple Horizon", "P1", "new"), ("Études Exemple Sahel", "P1", "contacted"),
                                       ("Centre Exemple Formation", "P2", "demo_scheduled"), ("Cabinet Exemple Conseil", "P3", "new")]:
                Prospect.objects.create(name=name, priority=prio, status=status, zone="Bamako", phone="70 00 00 00",
                                        next_follow_up=timezone.localdate())

        c1 = mk("conseiller@demo.ml", "Moussa", "Diarra", User.Role.COUNSELOR, "+223 70 00 00 01")
        c2 = mk("conseillere@demo.ml", "Awa", "Coulibaly", User.Role.COUNSELOR, "+223 70 00 00 02")
        from accounts.models import Role

        c1.agency_role = Role.objects.get(agency=agency, key="counselor")
        c1.save(update_fields=["agency_role"])
        c2.agency_role = Role.objects.get(agency=agency, key="supervisor")
        c2.save(update_fields=["agency_role"])
        cashier = mk("caisse@demo.ml", "Fatoumata", "Keïta", User.Role.COUNSELOR, "+223 70 00 00 03")
        cashier.agency_role = Role.objects.get(agency=agency, key="cashier")
        cashier.save(update_fields=["agency_role"])

        france = WorkflowTemplate.objects.get(agency=agency, name__startswith="France")
        canada = WorkflowTemplate.objects.get(agency=agency, name__startswith="Canada")
        maroc = WorkflowTemplate.objects.get(agency=agency, name__startswith="Maroc")

        def dossier(email, first, last, wf, counselor, **kw):
            d, _ = services.create_dossier(agency=agency, actor=admin, student_email=email, student_first_name=first,
                                           student_last_name=last, student_phone="+223 76 00 00 00",
                                           workflow=wf, counselor=counselor, **kw)
            d.student.set_password(PASSWORD)
            d.student.save()
            services.add_fee(d, admin, label="Accompagnement complet", amount=Decimal("750000"))
            return d

        def submit_all(d, user, approve=True):
            for req in d.document_requests.filter(stage=d.current_stage):
                services.submit_document(req, user, ContentFile(PDF, name=f"{req.name[:20]}.pdf"))
                if approve:
                    services.review_document(req, c1, approve=True)

        # 1. Étudiante au début : pièces à déposer (démo du parcours prioritaire)
        d1 = dossier("etudiant@demo.ml", "Fatoumata", "Keita", france, c1,
                     program="Licence Informatique", institution="Université de Lyon", intake="Septembre 2027",
                     guardian_name="Bakary Keita", guardian_phone="+223 66 00 00 00")
        services.record_payment(d1, c1, amount=Decimal("250000"), method="orange_money", reference="OM-123456")

        # 2. Pièce déposée à vérifier + une pièce retournée
        d2 = dossier("ibrahim@demo.ml", "Ibrahim", "Sangaré", france, c1, program="Master Finance", intake="Septembre 2027")
        reqs = list(d2.document_requests.filter(stage=d2.current_stage)[:2])
        services.submit_document(reqs[0], d2.student, ContentFile(PDF, name="passeport.pdf"))
        services.submit_document(reqs[1], d2.student, ContentFile(PDF, name="acte.pdf"))
        services.review_document(reqs[1], c1, approve=False, reason="Document illisible, merci de le scanner à nouveau.")

        # 3. Dossier avancé, étape en retard
        d3 = dossier("aminata@demo.ml", "Aminata", "Touré", canada, c2, program="DEC Techniques infirmières",
                     institution="Cégep de Sherbrooke", intake="Janvier 2027")
        submit_all(d3, d3.student)
        services.advance_stage(d3, c2)
        stage = d3.current_stage
        stage.due_date = timezone.localdate() - timedelta(days=6)
        stage.save()
        services.record_payment(d3, admin, amount=Decimal("750000"), method="bank", reference="VIR-889")

        # 4. Dossier bloqué
        d4 = dossier("oumar@demo.ml", "Oumar", "Cissé", maroc, c2, program="Pharmacie", intake="Octobre 2026")
        services.set_status(d4, admin, Dossier.Status.BLOCKED, "En attente de l'équivalence du baccalauréat")

        # 5. Dossier terminé (accueilli)
        d5 = dossier("mariam@demo.ml", "Mariam", "Dembélé", maroc, c1, program="Architecture", intake="Septembre 2026")
        services.record_payment(d5, c1, amount=Decimal("750000"), method="wave")
        while d5.current_stage:
            submit_all(d5, d5.student)
            services.advance_stage(d5, c1)
            d5.refresh_from_db()

        self.stdout.write(self.style.SUCCESS("Démo créée. Comptes (mot de passe : demo12345) :"))
        for u in User.objects.filter(agency=agency).order_by("role", "email"):
            self.stdout.write(f"  {u.get_role_display():<22} {u.email}")
        self.stdout.write(f"  {'Console NEURALIS':<22} console@demo.ml")
