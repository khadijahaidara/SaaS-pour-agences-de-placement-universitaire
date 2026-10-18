# Notes fonctionnelles — MVP

Ce document relie chaque fonction du MVP au parcours prioritaire et à un critère d'acceptation vérifiable
(règle commune du cadrage NEURALIS). Les tests automatisés correspondants sont indiqués entre crochets.

## Parcours prioritaire

1. Le conseiller crée le dossier à partir d'un modèle de parcours → un compte étudiant est créé, la liste de pièces et les étapes sont copiées, la 1re étape démarre avec une échéance.
2. Le conseiller transmet le lien d'activation (courriel + WhatsApp).
3. L'étudiant active son compte et voit « Votre prochaine action : Déposer : … ».
4. L'étudiant dépose une pièce depuis son téléphone → le conseiller est notifié, le tableau de suivi affiche « pièce(s) à vérifier ».
5. Le conseiller valide, ou retourne la pièce avec un motif → l'étudiant voit le motif et « Déposer à nouveau ».
6. Quand les pièces obligatoires de l'étape sont validées, le conseiller termine l'étape → l'étudiant voit la nouvelle étape, son échéance et la consigne.

## Critères d'acceptation

| # | Fonction | Critère | Test |
|---|---|---|---|
| A1 | Dossier | Créer un dossier copie les étapes et les pièces du modèle et démarre la 1re étape | `test_creates_student_stages_and_checklist_from_template` |
| A2 | Dossier | Un courriel appartenant à une autre agence ou à un membre du personnel est refusé | `test_rejects_email_of_user_from_another_agency` |
| A3 | Pièces | Un retour sans motif est refusé ; avec motif, l'étudiant le voit sur le portail | `test_full_priority_journey`, `test_journey_through_http` |
| A4 | Pièces | Seuls PDF/JPG/PNG ≤ 10 Mo dont le contenu correspond au format sont acceptés | `UploadValidationTests` |
| A5 | Étapes | Impossible de terminer une étape dont une pièce obligatoire n'est pas validée | `test_full_priority_journey` |
| A6 | Étapes | Seul le responsable peut forcer ; l'action est tracée en interne | `test_only_agency_admin_can_force` |
| A7 | Statuts | Bloquer exige un motif ; un dossier bloqué ne progresse pas et remonte en tête du suivi | `test_blocked_dossier_cannot_progress_and_needs_reason` |
| A8 | Statuts | La fin de la dernière étape passe le dossier à « Terminé » et le ferme aux modifications | `test_last_stage_completes_dossier` |
| A9 | Portail | La prochaine action suit l'ordre : pièce retournée → pièce demandée → solde → attente | `test_next_action_asks_payment_when_documents_ok` |
| A10 | Paiements | Un paiement ne dépasse jamais le solde ; l'annulation est réservée au responsable et motivée | `PaymentTests` |
| A11 | Suivi | Étape en retard et pièce à vérifier augmentent la priorité du dossier | `test_overdue_stage_and_review_raise_priority` |
| A12 | Sécurité | Une autre agence, un autre conseiller ou un autre étudiant obtient 404 sur un dossier ou un fichier | `IsolationTests` |
| A13 | Historique | Les événements internes (affectation, passage forcé) ne sont pas visibles par l'étudiant | `test_internal_events_hidden_from_student` |
| A14 | Comptes | Le lien d'activation permet de choisir son mot de passe et mène au bon espace | `test_student_activates_account_via_link` |

## Hors périmètre du MVP (V1 et plus tard)

- **V1 — Modèles et automatisations** : messages types par destination, relances automatiques avant échéance
  (tâche planifiée), duplication de modèles, import CSV de dossiers existants, export Excel.
- **V1 — Canaux** : notifications WhatsApp / SMS (fournisseur à choisir selon coût local), portail répondant (parent).
- **V1 — Finances** : échéancier de paiement, rapport d'encaissements par période et par conseiller.
- **Plus tard** : intégrations externes (plateformes de candidature, paiement mobile en ligne), signature électronique,
  application mobile, multi-agences pour réseaux de franchises.

## Hypothèses à confirmer en entretien (agences et étudiants)

- Les étapes et listes de pièces par défaut (`dossiers/defaults.py`) sont des points de départ, pas des vérités.
- Volume cible : agences de 1 à 10 conseillers et quelques centaines de dossiers ouverts ; au-delà, le calcul des
  priorités du tableau de suivi devra être déplacé en base (annotations SQL) ou mis en cache.
- La transmission du lien d'activation par WhatsApp est l'usage principal ; le courriel est secondaire.
- Les paiements sont saisis par l'agence (pas de paiement en ligne dans le MVP).
