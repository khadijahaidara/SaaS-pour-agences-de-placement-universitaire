# API REST NEURALIS Mobility — v1

Documentation interactive : `/api/docs/` (Swagger) ou `/api/redoc/`. Schéma OpenAPI : `/api/schema/`.

## Authentification

Le responsable d'agence crée une clé dans **Paramètres → API**. Elle n'est affichée qu'une fois.

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
