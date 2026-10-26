"""Rôles et permissions fines des équipes d'agence.

- Le responsable d'agence (AGENCY_ADMIN) a toujours toutes les permissions.
- Un membre de l'équipe (COUNSELOR) reçoit les permissions de son rôle d'agence
  (Conseiller, Caissier, Superviseur… ou un rôle créé par l'agence).
- Les étudiants et l'équipe NEURALIS n'ont aucune permission « agence ».
"""
PERMISSION_GROUPS = [
    ("Dossiers", [
        ("dossiers.view_all", "Voir tous les dossiers de l'agence (sinon : ceux qui lui sont confiés)"),
        ("dossiers.create", "Créer des dossiers"),
        ("dossiers.edit", "Modifier les dossiers, étapes et pièces"),
        ("dossiers.assign", "Réaffecter un dossier à un autre conseiller"),
        ("dossiers.change_status", "Bloquer, clôturer ou abandonner un dossier"),
        ("dossiers.force_advance", "Forcer le passage d'étape malgré des pièces manquantes"),
        ("dossiers.import", "Importer des dossiers (CSV)"),
        ("dossiers.export", "Exporter la liste des dossiers"),
        ("documents.review", "Valider ou refuser les pièces"),
        ("messages.send", "Envoyer des messages aux étudiants"),
    ]),
    ("Finances", [
        ("payments.view", "Voir les finances de l'agence"),
        ("payments.record", "Encaisser des paiements et ajouter des frais"),
        ("payments.cancel", "Annuler un paiement"),
        ("payments.export", "Exporter les paiements"),
    ]),
    ("Administration", [
        ("settings.manage", "Paramètres de l'agence, prestations, champs, messages, reçus"),
        ("workflows.manage", "Parcours par destination"),
        ("team.manage", "Inviter et gérer les membres de l'équipe"),
        ("roles.manage", "Créer et modifier les rôles"),
        ("integrations.manage", "Clés API et webhooks"),
        ("billing.manage", "Abonnement et factures NEURALIS"),
        ("audit.view", "Consulter le journal d'audit et la sécurité"),
    ]),
]

ALL_PERMISSIONS = [code for _, perms in PERMISSION_GROUPS for code, _ in perms]
PERMISSION_LABELS = {code: label for _, perms in PERMISSION_GROUPS for code, label in perms}

_COUNSELOR = [
    "dossiers.create", "dossiers.edit", "documents.review", "messages.send",
    "payments.view", "payments.record", "dossiers.export", "payments.export",
]

# Rôles proposés à chaque nouvelle agence (le premier est le rôle par défaut des invités).
DEFAULT_ROLES = [
    ("counselor", "Conseiller", "Suit les dossiers qui lui sont confiés, de l'inscription à l'arrivée.", _COUNSELOR),
    ("supervisor", "Superviseur", "Voit et pilote tous les dossiers, sans accès à l'administration.",
     _COUNSELOR + ["dossiers.view_all", "dossiers.assign", "dossiers.change_status", "dossiers.force_advance",
                   "dossiers.import", "payments.export"]),
    ("cashier", "Caissier", "Encaisse les paiements et édite les reçus pour toute l'agence.",
     ["dossiers.view_all", "payments.view", "payments.record", "payments.export"]),
    ("assistant", "Assistant administratif", "Collecte et vérifie les pièces de tous les dossiers.",
     ["dossiers.view_all", "dossiers.edit", "documents.review", "messages.send"]),
]
DEFAULT_ROLE_KEY = "counselor"


def ensure_default_roles(agency):
    """Crée les rôles par défaut manquants (idempotent)."""
    from .models import Role

    for key, name, description, perms in DEFAULT_ROLES:
        Role.objects.get_or_create(agency=agency, key=key, defaults={
            "name": name, "description": description, "permissions": perms, "is_system": key == DEFAULT_ROLE_KEY})


def default_role(agency):
    from .models import Role

    ensure_default_roles(agency)
    return Role.objects.get(agency=agency, key=DEFAULT_ROLE_KEY)
