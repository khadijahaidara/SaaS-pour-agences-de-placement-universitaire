import shutil
import tempfile
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from agencies.models import Agency
from dossiers import services
from dossiers.defaults import install_default_workflows
from dossiers.models import WorkflowTemplate

User = get_user_model()
PDF_BYTES = b"%PDF-1.4\n%test\n%%EOF\n"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

_MEDIA = tempfile.mkdtemp(prefix="placement-tests-")


def pdf(name="piece.pdf", content=PDF_BYTES):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@override_settings(MEDIA_ROOT=_MEDIA, EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BaseTestCase(TestCase):
    password = "Motdepasse-Test-42"

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.agency = Agency.objects.create(name="Agence A", slug="agence-a")
        cls.other_agency = Agency.objects.create(name="Agence B", slug="agence-b")
        install_default_workflows(cls.agency)
        install_default_workflows(cls.other_agency)
        cls.admin = cls.make_user("admin@a.ml", User.Role.AGENCY_ADMIN, cls.agency)
        cls.counselor = cls.make_user("conseiller@a.ml", User.Role.COUNSELOR, cls.agency)
        cls.counselor2 = cls.make_user("conseiller2@a.ml", User.Role.COUNSELOR, cls.agency)
        cls.other_admin = cls.make_user("admin@b.ml", User.Role.AGENCY_ADMIN, cls.other_agency)
        cls.workflow = WorkflowTemplate.objects.get(agency=cls.agency, name__startswith="Maroc")

    @classmethod
    def make_user(cls, email, role, agency):
        return User.objects.create_user(email=email, password=cls.password, role=role, agency=agency,
                                        first_name=email.split("@")[0].title())

    def make_dossier(self, email="etu@a.ml", counselor=None, agency=None, workflow=None, actor=None):
        agency = agency or self.agency
        dossier, _ = services.create_dossier(
            agency=agency, actor=actor or self.admin, student_email=email, student_first_name="Awa",
            student_last_name="Konaté", workflow=workflow or self.workflow,
            counselor=counselor if counselor is not None else self.counselor,
        )
        dossier.student.set_password(self.password)
        dossier.student.save()
        return dossier

    def login(self, user):
        self.client.force_login(user)

    def add_fee(self, dossier, amount=500000):
        return services.add_fee(dossier, self.admin, label="Accompagnement", amount=Decimal(amount))
