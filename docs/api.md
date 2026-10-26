# API REST NEURALIS Mobility — v1

Documentation interactive : `/api/docs/` (Swagger) ou `/api/redoc/`. Schéma OpenAPI : `/api/schema/`.

## Authentification

Disponible à partir de la formule **Pro**. Le responsable d'agence (ou un membre ayant la permission
`integrations.manage`) crée une clé dans **Intégrations → Clés API**. Elle n'est affichée qu'une fois.

```
Authorization: Api-Key nm_xxxxxxxx_…
```

Une clé donne accès à **toute l'agence** et à elle seule. Les actions faites via l'API apparaissent dans
l'historique des dossiers au nom du responsable qui a créé la clé. Quota par défaut : 600 requêtes/heure
par agence (`API_RATE_LIMIT`).

## Points d'accès

| Méthode | Chemin | Rôle |
|---|---|---|
| GET | `/api/v1/me/` | Agence de la clé, formule |
| GET | `/api/v1/dossiers/` | Liste (filtres `status`, `destination`, `q`, `updated_since`) |
| POST | `/api/v1/dossiers/` | Créer un dossier (+ prestation, champs personnalisés) |
| GET / PATCH | `/api/v1/dossiers/{référence}/` | Détail complet / modifier les informations |
| POST | `/api/v1/dossiers/{référence}/advance/` | Terminer l'étape en cours |
| POST | `/api/v1/dossiers/{référence}/status/` | Changer le statut (motif obligatoire si bloqué…) |
| POST | `/api/v1/dossiers/{référence}/payments/` | Enregistrer un paiement (reçu numéroté) |
| POST | `/api/v1/dossiers/{référence}/documents/` | Demander une pièce |
| POST | `/api/v1/dossiers/{référence}/apply-offer/` | Appliquer une prestation |
| GET | `/api/v1/payments/` | Paiements (`since`, `until`) |
| GET | `/api/v1/offers/`, `/workflows/`, `/custom-fields/` | Référentiels de l'agence |

Les règles métier sont les mêmes que dans l'interface : une violation renvoie `400` avec
`{"detail": "…", "code": "business_rule"}`.

## Exemple

```bash
curl -X POST https://monagence.neuralis-mobility.com/api/v1/dossiers/ \
  -H "Authorization: Api-Key $CLE" -H "Content-Type: application/json" \
  -d '{"student_email":"awa@exemple.ml","student_first_name":"Awa","student_last_name":"Diallo",
       "workflow_id":1,"offer_id":2,"custom_data":{"campus_france":"ML26-001"}}'
```

## Webhooks

**Intégrations → Webhooks** (formule Pro) : NEURALIS Mobility envoie un `POST` JSON à votre URL (https) à
chaque événement choisi.

```json
{"id": "6f0c…", "type": "payment.recorded", "created": "2026-10-26T10:12:00+00:00",
 "agency": "agence-demo-bamako",
 "data": {"dossier": "DOS-2026-0004", "receipt_number": "AD-2026-0007", "amount": 250000,
          "currency": "FCFA", "method": "orange_money", "balance": 500000}}
```

| Événement | Quand |
|---|---|
| `dossier.created` | Dossier créé (interface, import CSV ou API) |
| `dossier.stage_changed` | Étape terminée (`completed_stage`, `next_stage`, `forced`) |
| `dossier.status_changed` | Bloqué, refusé, terminé, abandonné… (`reason`) |
| `dossier.assigned` | Conseiller changé |
| `document.submitted` / `document.reviewed` | Pièce déposée / validée ou refusée |
| `payment.recorded` / `payment.cancelled` | Paiement encaissé / annulé |

En-têtes : `X-Neuralis-Event`, `X-Neuralis-Delivery` (identifiant unique, pour ignorer les doublons) et
`X-Neuralis-Signature: t=<horodatage>,v1=<signature>`.

Vérification (Python) :

```python
import hashlib, hmac, time

def verify(secret: str, header: str, body: bytes, tolerance=300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    expected = hmac.new(secret.encode(), f"{parts['t']}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"]) and abs(time.time() - int(parts["t"])) < tolerance
```

Répondez `2xx` en moins de 10 secondes. Sinon : nouvelles tentatives après 1 min, 5 min, 30 min, 2 h et 6 h ;
après 15 échecs consécutifs le webhook est suspendu et les responsables sont prévenus.
