import hashlib
import hmac
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class ApiKey(models.Model):
    """Clé d'accès à l'API, propre à une agence. Seule l'empreinte est stockée."""

    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField("nom", max_length=80, help_text="Ex. : Application mobile, Site web de l'agence")
    prefix = models.CharField(max_length=12, unique=True, editable=False)
    key_hash = models.CharField(max_length=64, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "clé API"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def hash(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def generate(cls, *, agency, name, created_by) -> tuple["ApiKey", str]:
        """Crée une clé et renvoie la valeur en clair (affichée une seule fois)."""
        prefix = secrets.token_hex(4)
        raw = f"nm_{prefix}_{secrets.token_urlsafe(32)}"
        key = cls.objects.create(agency=agency, name=name, prefix=prefix, key_hash=cls.hash(raw), created_by=created_by)
        return key, raw

    @classmethod
    def from_raw(cls, raw: str):
        parts = (raw or "").split("_", 2)
        if len(parts) != 3 or parts[0] != "nm":
            return None
        key = cls.objects.select_related("agency", "created_by").filter(prefix=parts[1], revoked_at__isnull=True).first()
        if key and hmac.compare_digest(key.key_hash, cls.hash(raw)):
            return key
        return None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def revoke(self):
        self.revoked_at = timezone.now()
        self.save(update_fields=["revoked_at"])
