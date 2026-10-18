"""Import de prospects depuis un fichier CSV ou un tableau Word (.docx).

Colonnes reconnues (en-têtes du fichier de prospection NEURALIS) :
Prospect, Zone, Téléphone, E-mail, Segment, Site Web, WhatsApp,
Décideur / fonction, Canal recommandé, Source vérification, Priorité Mobility.
Un prospect déjà présent (même nom, sans tenir compte de la casse) est mis à jour
sans écraser son étape commerciale ni ses notes.
"""
import csv
import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from django.db import transaction

from .models import Prospect

W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

HEADER_MAP = {
    "prospect": "name", "nom": "name", "entreprise": "name",
    "zone": "zone", "quartier": "zone",
    "telephone": "phone",
    "e-mail": "email", "email": "email", "courriel": "email",
    "segment": "segment",
    "site web": "website", "site": "website",
    "whatsapp": "whatsapp",
    "decideur / fonction": "decision_maker", "decideur": "decision_maker",
    "canal recommande": "channel",
    "source verification": "source", "source": "source",
    "priorite mobility": "priority", "priorite": "priority",
}

PLACEHOLDERS = {"non publie / a verifier", "non trouve lors de cette passe", "a verifier a partir du numero public",
                "non trouve lors de cette passe", "-", "—", "n/a"}


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", text).strip().lower()


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", (value or "")).strip()
    return "" if _norm(value) in PLACEHOLDERS else value


def _priority(value: str) -> str:
    m = re.search(r"P\s*([123])", value or "", re.I)
    return f"P{m.group(1)}" if m else Prospect.Priority.P3


def rows_from_docx(data: bytes) -> list[list[str]]:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    rows = []
    for table in root.iter(f"{W_NS}tbl"):
        for tr in table.iter(f"{W_NS}tr"):
            cells = []
            for tc in tr.findall(f"{W_NS}tc"):
                paragraphs = ["".join(t.text or "" for t in p.iter(f"{W_NS}t")) for p in tc.iter(f"{W_NS}p")]
                cells.append(" ".join(x for x in paragraphs if x).strip())
            rows.append(cells)
    return rows


def rows_from_csv(data: bytes) -> list[list[str]]:
    text = data.decode("utf-8-sig", errors="replace")
    dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t") if text.strip() else csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]


def parse_rows(rows: list[list[str]]) -> list[dict]:
    header_idx = next((i for i, r in enumerate(rows) if r and _norm(r[0]) in {"prospect", "nom", "entreprise"}), None)
    if header_idx is None:
        raise ValueError("En-tête introuvable : la première colonne doit s'appeler « Prospect ».")
    fields = [HEADER_MAP.get(_norm(h)) for h in rows[header_idx]]
    records = []
    for row in rows[header_idx + 1:]:
        rec = {}
        for field, value in zip(fields, row):
            if field:
                rec[field] = value
        name = _clean(rec.get("name", ""))
        if not name or _norm(name) in {"prospect", "nom"}:
            continue
        records.append({
            "name": name[:200],
            "zone": _clean(rec.get("zone", ""))[:150],
            "phone": _clean(rec.get("phone", ""))[:150],
            "email": _clean(rec.get("email", ""))[:200],
            "segment": _clean(rec.get("segment", ""))[:120],
            "website": _clean(rec.get("website", ""))[:300],
            "whatsapp": _clean(rec.get("whatsapp", ""))[:150],
            "decision_maker": _clean(rec.get("decision_maker", ""))[:300],
            "channel": _clean(rec.get("channel", ""))[:150],
            "source": _clean(rec.get("source", ""))[:500],
            "priority": _priority(rec.get("priority", "")),
        })
    return records


@transaction.atomic
def import_prospects(data: bytes, filename: str) -> dict:
    rows = rows_from_docx(data) if filename.lower().endswith(".docx") else rows_from_csv(data)
    records = parse_rows(rows)
    created = updated = 0
    for rec in records:
        existing = Prospect.objects.filter(name__iexact=rec["name"]).first()
        if existing:
            for k, v in rec.items():
                if v and k != "name":
                    setattr(existing, k, v)
            existing.save()
            updated += 1
        else:
            Prospect.objects.create(**rec)
            created += 1
    return {"created": created, "updated": updated, "total": len(records)}
