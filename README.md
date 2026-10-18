# NEURALIS Mobility — SaaS pour agences de placement universitaire

Application web (Django + PostgreSQL) qui permet à une agence d'accompagnement aux études à l'étranger de
suivre chaque étudiant **de la création du dossier jusqu'à l'accueil** dans le pays de destination, et à
l'étudiant de voir à tout moment **où en est son dossier, ce qui manque et ce qu'il doit faire ensuite**.

> Produit du programme NEURALIS (cadrage du 14/09/2026).

Trois espaces dans une même application :

- **Espace agence** (responsables et conseillers) : tableau de suivi priorisé, dossiers, pièces, étapes, paiements, équipe, parcours par destination, logo et couleur du portail.
- **Portail étudiant** aux couleurs de l'agence : « carte d'embarquement » Bamako → destination avec l'avancement, la prochaine action, le dépôt des pièces depuis le téléphone, les paiements et reçus.
- **Console NEURALIS** (équipe plateforme) : CRM de prospection des agences (import du fichier de 200 prospects, priorités P1/P2/P3, étapes commerciales, relances, WhatsApp en un clic), conversion d'un prospect en agence cliente, gestion des essais et abonnements.

Les agences peuvent aussi **créer leur espace seules** (`/inscription/`) : essai gratuit de 14 jours, parcours par défaut installés, prospect correspondant rattaché automatiquement dans le CRM.

## Ce que fait le MVP

| Fonction (cadrage) | Implémentation |
|---|---|
| Dossier étudiant | Profil, destination, établissement, programme, rentrée, répondant, conseiller responsable, notes internes |
| Documents et liste de contrôle | Pièces copiées du modèle de parcours, demandes ponctuelles, dépôt (PDF/JPG/PNG, 10 Mo), versions, validation ou retour **avec motif obligatoire** |
| Étapes configurables | Modèles par destination (France/Campus France, Canada, Maroc, Turquie fournis), modifiables par le responsable d'agence |
| Statuts et échéances | Statut du dossier (en cours, bloqué, refusé, terminé, abandonné), échéance par étape, retards calculés |
| Portail étudiant | « Votre prochaine action », avancement, pièces demandées et dépôt depuis le téléphone, paiements et reçus |
| Paiements de l'agence | Frais de service, encaissements (espèces, Orange Money, Moov Money, Wave, virement), soldes, reçus imprimables, annulation motivée |
| Historique et notifications | Journal de chaque action (interne ou visible par l'étudiant), notifications dans l'application + courriel |
| Tableau de suivi | Dossiers classés par urgence : bloqué, étape en retard, pièces à vérifier, pièces en retard, inactivité, sans conseiller |

**Parcours prioritaire couvert** : l'agence crée le dossier → les pièces sont demandées → l'étudiant dépose →
le conseiller valide ou retourne avec un motif → le dossier progresse → l'étudiant voit immédiatement la nouvelle
étape, son échéance et l'action suivante.

### Règles métier principales

- Une étape ne peut être terminée que si ses **pièces obligatoires sont validées** (le responsable peut forcer, l'action est tracée en interne).
- Un dossier **bloqué** ne progresse pas ; bloquer, refuser ou abandonner exige un **motif**.
- Un paiement ne peut **pas dépasser le solde** ; il n'est jamais supprimé, seulement **annulé avec motif** par le responsable.
- Le portail et les reçus rappellent que **le visa et l'admission ne sont jamais garantis**.
- Modifier un modèle de parcours n'altère pas les dossiers déjà ouverts.

### Rôles

| Rôle | Accès |
|---|---|
| Responsable d'agence | Tous les dossiers de l'agence, équipe, modèles de parcours, réaffectation, annulation de paiements, passage forcé |
| Conseiller | Uniquement les dossiers qui lui sont confiés |
| Étudiant | Uniquement son ou ses dossiers, via le portail |
| Administrateur plateforme (NEURALIS) | Admin Django (`/plateforme/admin/`), création des agences |

## Sécurité et confidentialité (passeports, relevés, admissions, visas)

- **Isolation** : toute lecture passe par `Dossier.objects.for_user(user)` ; un objet hors périmètre renvoie 404.
- **Pièces privées** : stockées hors du dossier public (`MEDIA_ROOT`) et servies uniquement par une vue qui vérifie les droits, avec `Cache-Control: private, no-store`.
- **Dépôts contrôlés** : extension, taille et signature réelle du fichier (un `.exe` renommé en `.pdf` est refusé) ; noms de fichiers aléatoires.
- Comptes activés par **lien d'invitation** (valable 7 jours, à envoyer aussi par WhatsApp) ; aucun mot de passe transmis.
- En production : HTTPS forcé, cookies sécurisés, HSTS, protection CSRF et clickjacking.

## Démarrage rapide (Windows / macOS / Linux)

```bash
python -m venv .venv
# Windows : .venv\Scripts\activate     — macOS/Linux : source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env        # (cp sur macOS/Linux) — DJANGO_DEBUG=1 utilise SQLite
python manage.py migrate
python manage.py seed_demo    # agence de démonstration
python manage.py runserver
```

Ouvrir http://127.0.0.1:8000 — mot de passe de tous les comptes de démonstration : `demo12345`

| Compte | Rôle |
|---|---|
| admin@demo.ml | Responsable d'agence |
| conseiller@demo.ml / conseillere@demo.ml | Conseillers |
| etudiant@demo.ml | Étudiante (pièces à déposer — idéal pour la démo du parcours) |
| console@demo.ml | Équipe NEURALIS : console CRM + agences |
| ibrahim@demo.ml, aminata@demo.ml, oumar@demo.ml, mariam@demo.ml | Autres étudiants à différents stades |

### Avec PostgreSQL / Docker

```bash
cp .env.example .env    # puis mettre DJANGO_DEBUG=0 et un vrai DJANGO_SECRET_KEY
docker compose up --build
docker compose exec web python manage.py seed_demo
```

Sans Docker, définir `DATABASE_URL=postgres://utilisateur:motdepasse@hote:5432/base`.

### Importer le fichier de prospection

Dans la console : **Importer des prospects** et déposer le fichier Word (tableau) ou CSV. En ligne de commande :

```bash
python manage.py import_prospects "NEURALIS_Mobility_200_Agences.docx"
```

Le fichier de prospects n'est **pas** versionné dans le dépôt (données de contact) : importez-le sur chaque environnement.

### Ouvrir une agence cliente

```bash
python manage.py create_agency --name "Agence Horizon" --admin-email responsable@horizon.ml \
    --admin-first-name Awa --admin-last-name Traoré --base-url https://placement.neuralis-mali.com
```

La commande crée l'agence en essai, son responsable, les 4 parcours par défaut et affiche le lien d'activation. Depuis la console, le bouton « Créer son espace agence » d'une fiche prospect fait la même chose.

Pour créer un compte d'équipe NEURALIS : `python manage.py createsuperuser`.

## Tests

```bash
python manage.py test
```

37 tests couvrent le parcours prioritaire (services et HTTP), l'isolation entre agences, conseillers et étudiants,
la protection des fichiers, la validation des dépôts, les règles de paiement, les alertes, l'activation des comptes, l'inscription libre (anti-abus, essai), le blocage à expiration, l'import de prospects, le pipeline commercial et la conversion en agence.
La CI GitHub (`.github/workflows/tests.yml`) les exécute sur PostgreSQL à chaque push.

## Structure

```
config/        paramètres (variables d'environnement), URLs
accounts/      utilisateur par courriel + rôles, connexion, activation par lien
agencies/      agence (locataire), inscription libre, essai/abonnement, marque du portail, équipe, parcours
console/       console NEURALIS : CRM prospects, import CSV/Word, agences clientes
dossiers/      cœur métier : modèles, services (règles), espace agence, permissions, tests
  services.py  toutes les actions métier (transaction + journal + notification)
  defaults.py  modèles de parcours par défaut (hypothèses à valider en entretien)
portal/        portail étudiant
templates/     interface (HTML, français, mobile d'abord) — layouts app / auth / portail
static/        CSS, JS (listes déroulantes avec recherche, menus, fenêtres modales) et polices auto-hébergées, sans CDN
docs/          notes fonctionnelles et suite du produit
```

## Production — points d'attention

- Sauvegarder **la base et `MEDIA_ROOT`** (les pièces) chaque jour ; tester la restauration.
- Configurer un SMTP réel (`EMAIL_*`) ; sinon les courriels s'affichent seulement dans la console.
- Servir derrière un proxy HTTPS (Nginx, Caddy…) qui transmet `X-Forwarded-Proto`.
- Ne jamais exposer `MEDIA_ROOT` en statique.

Voir [`docs/fonctionnel.md`](docs/fonctionnel.md) pour les critères d'acceptation et la feuille de route V1.
