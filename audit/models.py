"""Journal d'audit : qui a fait quoi, quand, depuis où."""
from django.conf import settings
from django.db import models

ACTIONS = {
    # Connexion et sécurité
    "auth.login": "Connexion",
    "auth.logout": "Déconnexion",
    "auth.login_failed": "Échec de connexion",
    "auth.locked": "Connexions bloquées (trop d'échecs)",
    "auth.2fa_enabled": "Double authentification activée",
    "auth.2fa_disabled": "Double authentification désactivée",
    "auth.2fa_failed": "Code de double authentification erroné",
    "auth.recovery_used": "Code de secours utilisé",
    "auth.password_changed": "Mot de passe modifié",
    "auth.session_revoked": "Session déconnectée à distance",
    # Dossiers et pièces
    "dossier.created": "Dossier créé",
    "dossier.status_changed": "Statut de dossier modifié",
    "dossier.assigned": "Dossier réaffecté",
    "dossier.imported": "Import de dossiers",
    "dossier.exported": "Export des dossiers",
    "document.downloaded": "Pièce téléchargée",
    "document.reviewed": "Pièce vérifiée",
    # Finances
    "payment.recorded": "Paiement enregistré",
    "payment.cancelled": "Paiement annulé",
    "payment.exported": "Export des paiements",
    # Équipe et administration
    "team.invited": "Membre invité",
    "team.role_changed": "Rôle d'un membre modifié",
    "team.toggled": "Accès d'un membre modifié",
    "role.saved": "Rôle enregistré",
    "role.deleted": "Rôle supprimé",
    "settings.updated": "Paramètres modifiés",
    "security.updated": "Politique de sécurité modifiée",
    "api_key.created": "Clé API créée",
    "api_key.revoked": "Clé API révoquée",
    "webhook.created": "Webhook créé",
    "webhook.updated": "Webhook modifié",
    "webhook.deleted": "Webhook supprimé",
    "webhook.disabled": "Webhook désactivé automatiquement",
    # Abonnement
    "billing.plan_requested": "Changement de formule demandé",
    "billing.plan_changed": "Formule modifiée",
    "billing.invoice_issued": "Facture émise",
    "billing.invoice_paid": "Facture payée",
    "billing.invoice_void": "Facture annulée",
}

ACTION_GROUPS = [
    ("auth", "Connexions et sécurité"),
    ("dossier", "Dossiers"),
    ("document", "Pièces"),
    ("payment", "Paiements"),
    ("team", "Équipe"),
    ("role", "Rôles"),
    ("settings", "Paramètres"),
    ("security", "Sécurité"),
    ("api_key", "API"),
    ("webhook", "Webhooks"),
    ("billing", "Abonnement"),
]

SENSITIVE = {"auth.login_failed", "auth.locked", "auth.2fa_failed", "payment.cancelled", "auth.2fa_disabled",
             "api_key.created", "webhook.disabled", "team.role_changed", "security.updated", "dossier.exported",
             "payment.exported"}


class AuditLog(models.Model):
    agency = models.ForeignKey("agencies.Agency", on_delete=models.CASCADE, null=True, blank=True,
                               related_name="audit_logs")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+")
    actor_label = models.CharField(max_length=200, blank=True)
    action = models.CharField(max_length=40, db_index=True)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.CharField(max_length=60, blank=True)
    target_label = models.CharField(max_length=200, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "entrée du journal d'audit"
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["agency", "-created_at"]), models.Index(fields=["agency", "action"])]

    def __str__(self) -> str:
        return f"{self.created_at:%d/%m/%Y %H:%M} {self.action}"

    @property
    def label(self) -> str:
        return ACTIONS.get(self.action, self.action)

    @property
    def is_sensitive(self) -> bool:
        return self.action in SENSITIVE

    @property
    def details(self) -> str:
        return " · ".join(f"{k} : {v}" for k, v in (self.metadata or {}).items() if v not in ("", None))
