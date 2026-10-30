import hashlib
import secrets

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone

from .rbac import ALL_PERMISSIONS


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

    class Theme(models.TextChoices):
        AUTO = "auto", "Automatique (comme l'appareil)"
        LIGHT = "light", "Clair"
        DARK = "dark", "Sombre"

    class Density(models.TextChoices):
        COMFORTABLE = "comfortable", "Confortable"
        COMPACT = "compact", "Compact"

    ui_theme = models.CharField("thème", max_length=10, choices=Theme.choices, default=Theme.AUTO)
    ui_density = models.CharField("densité d'affichage", max_length=12, choices=Density.choices,
                                  default=Density.COMFORTABLE)
    dashboard_layout = models.JSONField("blocs du tableau de bord", default=list, blank=True)

    agency_role = models.ForeignKey(
        "accounts.Role", verbose_name="rôle dans l'agence", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="members",
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

    # ----------------------------------------------------------------- #
    # Permissions fines
    # ----------------------------------------------------------------- #
    @property
    def agency_permissions(self) -> frozenset:
        cached = getattr(self, "_agency_perms_cache", None)
        if cached is not None:
            return cached
        if not self.is_active or self.role in {self.Role.STUDENT, self.Role.PLATFORM_ADMIN}:
            perms = frozenset()
        elif self.role == self.Role.AGENCY_ADMIN:
            perms = frozenset(ALL_PERMISSIONS)
        else:
            role = self.agency_role
            if role is None or role.agency_id != self.agency_id:
                from .rbac import DEFAULT_ROLES

                role_perms = DEFAULT_ROLES[0][3]
            else:
                role_perms = role.permissions
            perms = frozenset(p for p in role_perms if p in ALL_PERMISSIONS)
        self._agency_perms_cache = perms
        return perms

    def has_agency_perm(self, code: str) -> bool:
        return code in self.agency_permissions

    @property
    def role_label(self) -> str:
        if self.role == self.Role.COUNSELOR and self.agency_role_id:
            return self.agency_role.name
        return self.get_role_display()

    @property
    def has_2fa(self) -> bool:
        device = getattr(self, "totp_device", None)
        return bool(device and device.confirmed_at)


class Role(models.Model):
    """Rôle d'une agence : un ensemble de permissions attribué aux membres de l'équipe."""

    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, related_name="roles")
    key = models.SlugField(max_length=40, blank=True, help_text="Identifiant des rôles fournis par NEURALIS.")
    name = models.CharField("nom du rôle", max_length=60)
    description = models.CharField("description", max_length=200, blank=True)
    permissions = models.JSONField("permissions", default=list, blank=True)
    is_system = models.BooleanField("rôle par défaut", default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "rôle d'agence"
        ordering = ["-is_system", "name"]
        constraints = [
            models.UniqueConstraint(fields=["agency", "name"], name="unique_role_name_per_agency"),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        self.permissions = sorted({p for p in (self.permissions or []) if p in ALL_PERMISSIONS})


# --------------------------------------------------------------------------- #
# Double authentification (TOTP) et sessions
# --------------------------------------------------------------------------- #
def _hash_code(code: str) -> str:
    return hashlib.sha256(code.replace("-", "").strip().lower().encode()).hexdigest()


class TOTPDevice(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="totp_device")
    secret = models.CharField(max_length=64)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    last_used_step = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "application d'authentification"

    def totp(self):
        import pyotp

        return pyotp.TOTP(self.secret)

    def provisioning_uri(self) -> str:
        from django.conf import settings

        return self.totp().provisioning_uri(name=self.user.email, issuer_name=settings.SITE_NAME)

    def verify(self, code: str) -> bool:
        """Vérifie un code à 6 chiffres (±30 s) et refuse sa réutilisation."""
        code = (code or "").replace(" ", "").strip()
        if not code.isdigit() or len(code) != 6:
            return False
        totp = self.totp()
        now = timezone.now()
        for drift in (-1, 0, 1):
            at = now + timezone.timedelta(seconds=30 * drift)
            step = int(at.timestamp()) // 30
            if step > self.last_used_step and secrets.compare_digest(totp.at(at), code):
                self.last_used_step = step
                self.save(update_fields=["last_used_step"])
                return True
        return False


class RecoveryCode(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="recovery_codes")
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)

    @classmethod
    def regenerate(cls, user, count: int = 10) -> list[str]:
        cls.objects.filter(user=user).delete()
        codes = []
        for _ in range(count):
            raw = secrets.token_hex(5)
            code = f"{raw[:5]}-{raw[5:]}"
            codes.append(code)
            cls.objects.create(user=user, code_hash=_hash_code(code))
        return codes

    @classmethod
    def consume(cls, user, code: str) -> bool:
        match = cls.objects.filter(user=user, code_hash=_hash_code(code or ""), used_at__isnull=True).first()
        if not match:
            return False
        match.used_at = timezone.now()
        match.save(update_fields=["used_at"])
        return True


class UserSession(models.Model):
    """Session ouverte (appareil) : permet de lister et de déconnecter les autres appareils."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sessions")
    session_key = models.CharField(max_length=64, unique=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-last_seen"]

    @property
    def device_label(self) -> str:
        ua = self.user_agent.lower()
        browser = next((n for k, n in [("edg/", "Edge"), ("opr/", "Opera"), ("chrome", "Chrome"),
                                        ("firefox", "Firefox"), ("safari", "Safari")] if k in ua), "Navigateur")
        system = next((n for k, n in [("android", "Android"), ("iphone", "iPhone"), ("ipad", "iPad"),
                                       ("windows", "Windows"), ("mac os", "macOS"), ("linux", "Linux")] if k in ua), "")
        return f"{browser} · {system}" if system else browser

    def revoke(self):
        from django.contrib.sessions.backends.db import SessionStore

        SessionStore(session_key=self.session_key).delete()
        self.delete()
