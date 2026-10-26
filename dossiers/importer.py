"""Import de dossiers depuis un fichier CSV (Excel « CSV UTF-8 » ou séparateur ;)."""
import csv
import io
import unicodedata

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction

from core.exceptions import BusinessRuleError

MAX_ROWS = 500
MAX_BYTES = 1024 * 1024
User = get_user_model()

COLUMNS = [
    ("prenom", "Prénom", True), ("nom", "Nom", True), ("email", "Courriel", True), ("telephone", "Téléphone", False),
    ("parcours", "Parcours (nom ou pays)", True), ("conseiller", "Courriel du conseiller", False),
    ("ville", "Ville", False), ("etablissement", "Établissement", False), ("programme", "Programme", False),
    ("rentree", "Rentrée", False), ("prestation", "Prestation", False), ("tuteur", "Parent / tuteur", False),
    ("tel_tuteur", "Téléphone du tuteur", False),
]
ALIASES = {
    "prenom": ["prenom", "first_name", "prenoms"], "nom": ["nom", "last_name", "nom de famille"],
    "email": ["email", "courriel", "e-mail", "mail"], "telephone": ["telephone", "tel", "phone", "whatsapp"],
    "parcours": ["parcours", "destination", "pays", "workflow"], "conseiller": ["conseiller", "counselor"],
    "ville": ["ville", "city"], "etablissement": ["etablissement", "universite", "ecole", "institution"],
    "programme": ["programme", "formation", "filiere", "program"], "rentree": ["rentree", "intake", "session"],
    "prestation": ["prestation", "offre", "pack"], "tuteur": ["tuteur", "parent", "parent / tuteur"],
    "tel_tuteur": ["tel_tuteur", "telephone du tuteur", "telephone tuteur", "tel tuteur"],
}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", (value or "").strip().lower())
    return "".join(c for c in value if not unicodedata.combining(c)).replace("_", " ").strip()


HEADER_MAP = {_norm(alias): key for key, aliases in ALIASES.items() for alias in aliases}


def template_csv() -> str:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";")
    writer.writerow([key for key, _, _ in COLUMNS])
    writer.writerow(["Awa", "Traoré", "awa.traore@exemple.ml", "+223 70 00 00 00", "France", "", "Paris",
                     "Université Paris-Saclay", "Licence informatique", "Septembre 2027", "", "Moussa Traoré",
                     "+223 76 00 00 00"])
    return "﻿" + out.getvalue()


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise BusinessRuleError("Encodage du fichier non reconnu : enregistrez-le en « CSV UTF-8 ».")


def parse(uploaded) -> list[dict]:
    raw = uploaded.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise BusinessRuleError("Fichier trop volumineux (1 Mo maximum).")
    text = _decode(raw)
    sample = text[:4096]
    delimiter = ";" if sample.count(";") >= sample.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        header = next(reader)
    except StopIteration:
        raise BusinessRuleError("Le fichier est vide.") from None
    keys = [HEADER_MAP.get(_norm(h)) for h in header]
    missing = [label for key, label, required in COLUMNS if required and key not in keys]
    if missing:
        raise BusinessRuleError("Colonnes obligatoires absentes : " + ", ".join(missing)
                                + ". Téléchargez le modèle pour voir le format attendu.")
    rows = []
    for line_no, values in enumerate(reader, start=2):
        if not any(v.strip() for v in values):
            continue
        row = {k: (values[i].strip() if i < len(values) else "") for i, k in enumerate(keys) if k}
        row["line"] = line_no
        rows.append(row)
        if len(rows) > MAX_ROWS:
            raise BusinessRuleError(f"{MAX_ROWS} lignes maximum par import : découpez le fichier.")
    if not rows:
        raise BusinessRuleError("Aucune ligne de données dans le fichier.")
    return rows


def validate(rows: list[dict], *, agency, actor) -> list[dict]:
    """Ajoute à chaque ligne : erreurs, avertissements et identifiants résolus."""
    from agencies.models import ServiceOffer
    from billing.services import effective_plan, usage

    from .models import WorkflowTemplate

    workflows = list(WorkflowTemplate.objects.filter(agency=agency, is_active=True))
    staff = {u.email.lower(): u for u in User.objects.filter(
        agency=agency, is_active=True, role__in=[User.Role.AGENCY_ADMIN, User.Role.COUNSELOR])}
    offers = {_norm(o.name): o for o in ServiceOffer.objects.filter(agency=agency, is_active=True)}
    can_assign = actor.has_agency_perm("dossiers.assign")
    seen = set()
    plan = effective_plan(agency)
    remaining = None if plan.max_active_dossiers is None else max(
        0, plan.max_active_dossiers - usage(agency)["dossiers"]["used"])

    for row in rows:
        errors, warnings = [], []
        for key, label, required in COLUMNS:
            if required and not row.get(key):
                errors.append(f"{label} manquant")
        email = row.get("email", "").lower()
        if email:
            try:
                validate_email(email)
            except ValidationError:
                errors.append("Courriel invalide")
            if email in seen:
                errors.append("Courriel en double dans le fichier")
            seen.add(email)
            existing = User.objects.filter(email__iexact=email).first()
            if existing and (existing.agency_id != agency.id or existing.role != User.Role.STUDENT):
                errors.append("Courriel déjà utilisé par un compte hors de vos étudiants")
            elif existing:
                warnings.append("Étudiant déjà inscrit : un nouveau dossier lui sera ajouté")
        wf_name = _norm(row.get("parcours", ""))
        workflow = next((w for w in workflows if _norm(w.name) == wf_name), None) or next(
            (w for w in workflows if _norm(w.destination_country) == wf_name), None)
        if row.get("parcours") and workflow is None:
            errors.append(f"Parcours « {row['parcours']} » introuvable")
        counselor = None
        if row.get("conseiller"):
            counselor = staff.get(row["conseiller"].lower())
            if counselor is None:
                errors.append(f"Conseiller « {row['conseiller']} » introuvable")
        if not can_assign:
            if counselor and counselor != actor:
                warnings.append("Dossier attribué à vous-même (pas de droit de réaffectation)")
            counselor = actor
        offer = None
        if row.get("prestation"):
            offer = offers.get(_norm(row["prestation"]))
            if offer is None:
                errors.append(f"Prestation « {row['prestation']} » introuvable")
        if not errors and remaining is not None:
            if remaining <= 0:
                errors.append(f"Limite de la formule {plan.name} atteinte")
            else:
                remaining -= 1
        row.update({"errors": errors, "warnings": warnings, "workflow_id": workflow.pk if workflow else None,
                    "workflow_name": workflow.name if workflow else "", "counselor_id": counselor.pk if counselor else None,
                    "counselor_name": str(counselor) if counselor else "", "offer_id": offer.pk if offer else None})
    return rows


def run_import(rows: list[dict], *, agency, actor) -> dict:
    from agencies import customization as custom
    from agencies.models import ServiceOffer

    from . import services
    from .models import WorkflowTemplate

    created, failed, accounts = 0, [], 0
    for row in rows:
        if row.get("errors"):
            continue
        try:
            with transaction.atomic():
                dossier, new_account = services.create_dossier(
                    agency=agency, actor=actor, student_email=row["email"], student_first_name=row["prenom"],
                    student_last_name=row["nom"], student_phone=row.get("telephone", ""),
                    workflow=WorkflowTemplate.objects.get(pk=row["workflow_id"], agency=agency),
                    counselor=User.objects.filter(pk=row["counselor_id"], agency=agency).first() if row["counselor_id"] else None,
                    destination_city=row.get("ville", "")[:100], institution=row.get("etablissement", "")[:200],
                    program=row.get("programme", "")[:200], intake=row.get("rentree", "")[:50],
                    guardian_name=row.get("tuteur", "")[:150], guardian_phone=row.get("tel_tuteur", "")[:30],
                )
                if row.get("offer_id"):
                    custom.apply_offer(dossier, actor, ServiceOffer.objects.get(pk=row["offer_id"], agency=agency))
        except BusinessRuleError as e:
            failed.append({"line": row["line"], "error": str(e)})
        else:
            created += 1
            accounts += int(new_account)
    return {"created": created, "failed": failed, "accounts": accounts}
