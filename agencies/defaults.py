"""Contenus installés par défaut dans chaque nouvelle agence (modifiables ensuite)."""

DEFAULT_MESSAGE_TEMPLATES = [
    {
        "name": "Bienvenue et activation du compte",
        "channel": "whatsapp",
        "subject": "",
        "body": ("Bonjour {prenom}, bienvenue chez {agence} ! Votre dossier {reference} pour {destination} est ouvert. "
                 "Suivez son avancement et déposez vos pièces ici : {lien_portail}"),
    },
    {
        "name": "Relance des pièces manquantes",
        "channel": "whatsapp",
        "subject": "",
        "body": ("Bonjour {prenom}, pour avancer sur votre dossier {reference}, il nous manque : {pieces_manquantes}. "
                 "Vous pouvez les déposer directement depuis votre téléphone : {lien_portail}. Merci ! {conseiller}, {agence}"),
    },
    {
        "name": "Rappel de paiement",
        "channel": "whatsapp",
        "subject": "",
        "body": ("Bonjour {prenom}, il reste {solde} à régler sur votre dossier {reference}. "
                 "Merci de passer à l'agence ou de payer par Orange Money / Wave. {agence}"),
    },
    {
        "name": "Nouvelle étape franchie",
        "channel": "email",
        "subject": "Votre dossier {reference} avance",
        "body": ("Bonjour {prenom},\n\nBonne nouvelle : votre dossier passe à l'étape « {etape} » "
                 "(échéance prévue : {echeance}).\n\nRetrouvez le détail sur votre portail : {lien_portail}\n\n{conseiller}\n{agence}"),
    },
]


def install_default_templates(agency, MessageTemplate=None):
    if MessageTemplate is None:
        from .models import MessageTemplate
    for tpl in DEFAULT_MESSAGE_TEMPLATES:
        MessageTemplate.objects.get_or_create(agency=agency, name=tpl["name"], defaults={
            "channel": tpl["channel"], "subject": tpl["subject"], "body": tpl["body"]})
