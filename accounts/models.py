from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra):
        if not email:
            raise ValueError("Le courriel est obligatoire.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra):
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email, password=None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        extra.setdefault("role", User.Role.PLATFORM_ADMIN)
        return self._create_user(email, password, **extra)


class User(AbstractUser):
    """Utilisateur identifié par son courriel.

    Rôles :
    - PLATFORM_ADMIN : équipe NEURALIS (admin Django, toutes les agences) ;
    - AGENCY_ADMIN : responsable d'agence (équipe, modèles, tous les dossiers, paiements) ;
    - COUNSELOR : conseiller (dossiers qui lui sont confiés) ;
    - STUDENT : étudiant (son ou ses dossiers uniquement, via le portail).
    """

    class Role(models.TextChoices):
        PLATFORM_ADMIN = "platform_admin", "Administrateur plateforme"
        AGENCY_ADMIN = "agency_admin", "Responsable d'agence"
        COUNSELOR = "counselor", "Conseiller"
        STUDENT = "student", "Étudiant"

    username = None
    email = models.EmailField("courriel", unique=True)
    phone = models.CharField("téléphone / WhatsApp", max_length=30, blank=True)
    notify_email = models.BooleanField("recevoir les notifications par courriel", default=True)
    daily_digest = models.BooleanField("recevoir le résumé quotidien", default=True,
                                       help_text="Conseillers et responsables : les dossiers à traiter, chaque matin.")
    role = models.CharField("rôle", max_length=20, choices=Role.choices, default=Role.STUDENT)
    agency = models.ForeignKey(
        "agencies.Agency",
        verbose_name="agence",
        on_delete=models.PROTECT,
        related_name="users",
        null=True,
        blank=True,
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    objects = UserManager()

    class Meta:
        verbose_name = "utilisateur"
        constraints = [
            models.CheckConstraint(
                name="non_platform_user_has_agency",
                condition=models.Q(role="platform_admin") | models.Q(agency__isnull=False),
            )
        ]

    def __str__(self) -> str:
        return self.get_full_name() or self.email

    @property
    def is_agency_staff(self) -> bool:
        return self.role in {self.Role.AGENCY_ADMIN, self.Role.COUNSELOR}

    @property
    def is_agency_admin(self) -> bool:
        return self.role == self.Role.AGENCY_ADMIN

    @property
    def is_student(self) -> bool:
        return self.role == self.Role.STUDENT
