"""Modèles de parcours proposés par défaut à une nouvelle agence.

Ce sont des points de départ à faire valider par les agences pendant les
entretiens (hypothèses) : chaque agence peut ensuite les adapter dans
« Parcours ».
"""
from django.db import transaction

from .models import DocumentTemplate, StageTemplate, WorkflowTemplate

COMMON_DOCS = [
    ("Passeport en cours de validité", "Page d'identité, validité ≥ 6 mois après la date de départ", True, 1),
    ("Acte de naissance", "", True, 1),
    ("Photo d'identité", "Fond blanc, format passeport", True, 1),
    ("Relevés de notes", "Trois dernières années", True, 1),
    ("Diplôme du baccalauréat ou attestation", "", True, 1),
]

DEFAULT_WORKFLOWS = [
    {
        "name": "France — Campus France",
        "country": "France",
        "stages": [
            ("Constitution du dossier", 14, "Envoyez toutes les pièces demandées ci-dessous."),
            ("Candidature Études en France", 21, "Votre conseiller saisit et vérifie vos candidatures sur la plateforme."),
            ("Entretien Campus France", 21, "Préparez votre projet d'études : votre conseiller vous contactera pour une simulation."),
            ("Réponses des établissements", 45, "Nous suivons les réponses des établissements pour vous."),
            ("Demande de visa", 30, "Préparez les justificatifs financiers et le logement."),
            ("Préparation du départ", 14, "Billet, assurance, documents à emporter."),
            ("Arrivée et accueil", 14, "Confirmez votre arrivée à votre conseiller."),
        ],
        "docs": COMMON_DOCS + [
            ("Lettre de motivation", "Une par formation visée", True, 2),
            ("Attestation de niveau de français", "TCF / DELF si demandé", False, 2),
            ("Justificatif de ressources", "Attestation bancaire ou prise en charge", True, 5),
            ("Attestation de logement", "", True, 5),
        ],
    },
    {
        "name": "Canada — Permis d'études",
        "country": "Canada",
        "stages": [
            ("Constitution du dossier", 14, "Envoyez toutes les pièces demandées."),
            ("Candidature à l'établissement", 30, ""),
            ("Lettre d'admission", 45, ""),
            ("CAQ (Québec) le cas échéant", 30, ""),
            ("Demande de permis d'études", 60, "Biométrie et justificatifs financiers."),
            ("Préparation du départ", 14, ""),
            ("Arrivée et accueil", 14, ""),
        ],
        "docs": COMMON_DOCS + [
            ("Preuve de capacité financière", "", True, 5),
            ("Lettre d'explication", "", True, 5),
        ],
    },
    {
        "name": "Maroc — Inscription",
        "country": "Maroc",
        "stages": [
            ("Constitution du dossier", 10, ""),
            ("Candidature / préinscription", 21, ""),
            ("Admission", 30, ""),
            ("Préparation du départ", 14, ""),
            ("Arrivée et accueil", 14, ""),
        ],
        "docs": COMMON_DOCS,
    },
    {
        "name": "Turquie — Inscription",
        "country": "Turquie",
        "stages": [
            ("Constitution du dossier", 10, ""),
            ("Candidature", 21, ""),
            ("Lettre d'acceptation", 30, ""),
            ("Demande de visa", 30, ""),
            ("Préparation du départ", 14, ""),
            ("Arrivée et accueil (permis de séjour)", 30, ""),
        ],
        "docs": COMMON_DOCS + [("Justificatif de ressources", "", True, 4)],
    },
]


@transaction.atomic
def install_default_workflows(agency) -> int:
    created = 0
    for wf in DEFAULT_WORKFLOWS:
        tpl, is_new = WorkflowTemplate.objects.get_or_create(
            agency=agency, name=wf["name"], defaults={"destination_country": wf["country"]}
        )
        if not is_new:
            continue
        created += 1
        for i, (name, days, instructions) in enumerate(wf["stages"], start=1):
            StageTemplate.objects.create(workflow=tpl, order=i, name=name, default_duration_days=days,
                                         student_instructions=instructions)
        for name, desc, required, stage_order in wf["docs"]:
            DocumentTemplate.objects.create(workflow=tpl, name=name, description=desc, is_required=required,
                                            stage_order=stage_order)
    return created
