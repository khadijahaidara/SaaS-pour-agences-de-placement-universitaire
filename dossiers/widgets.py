"""Blocs du tableau de bord, que chaque membre choisit et ordonne."""
WIDGETS = [
    # clé, libellé, description, taille (full / wide / narrow), permission requise
    ("stats", "Indicateurs clés", "Dossiers en cours, pièces à vérifier, retards, encaissements.", "full", None),
    ("priority", "À traiter en priorité", "Les dossiers en alerte, du plus urgent au moins urgent.", "wide", None),
    ("destinations", "Destinations", "Répartition des dossiers en cours par pays.", "narrow", None),
    ("deadlines", "Échéances à venir", "Étapes et pièces attendues dans les 14 prochains jours.", "wide", None),
    ("stages", "Où en sont les dossiers", "Nombre de dossiers par étape.", "narrow", None),
    ("payments", "Encaissements", "Montants encaissés sur les 6 derniers mois.", "narrow", "payments.view"),
    ("team", "Charge de l'équipe", "Dossiers en cours par conseiller.", "narrow", "dossiers.view_all"),
    ("activity", "Activité récente", "Les dernières actions sur vos dossiers.", "narrow", None),
]
DEFAULT_LAYOUT = ["stats", "priority", "destinations", "stages", "activity"]
_BY_KEY = {w[0]: w for w in WIDGETS}


def available(user) -> list[dict]:
    return [{"key": k, "label": label, "description": d, "size": size}
            for k, label, d, size, perm in WIDGETS if perm is None or user.has_agency_perm(perm)]


def user_layout(user) -> list[dict]:
    allowed = {w["key"]: w for w in available(user)}
    keys = [k for k in (user.dashboard_layout or DEFAULT_LAYOUT) if k in allowed]
    return [allowed[k] for k in dict.fromkeys(keys)]


def clean_layout(user, keys) -> list[str]:
    allowed = {w["key"] for w in available(user)}
    return [k for k in dict.fromkeys(keys) if k in allowed][:len(WIDGETS)]
