# Changements avant la soutenance — récapitulatif

Document de synthèse du travail réalisé sur `backend/`+`frontend/` (l'application
déployée) entre l'état des lieux (Tâche 0) et ce jour, suivant le plan de tâches
transmis avant la soutenance. Chaque tâche a été committée séparément, poussée,
et vérifiée verte sur la CI GitHub Actions (workflow « Validation ») avant de
passer à la suivante — voir l'historique git pour le détail exact des diffs.

Rappel de périmètre (inchangé) : `evaluation/`, `rag/`, `referentiel/`,
`validation/`, `securite/`, `corpus/` forment un laboratoire de validation
séparé, jamais câblé dans l'application déployée. Les tâches ci-dessous portent
sur l'application réelle, sauf la Tâche 7 (préparation d'une mesure du moteur
de production, toujours sans lien avec le laboratoire).

Un second document de cadrage (« Fiabiliser les quatre référentiels ») a été
transmis après la Tâche 9, pour étendre le filtre d'éligibilité (Tâche 8) aux
trois référentiels non-RGPD : Tâches F1 à F3 ci-dessous, mêmes règles de
méthode (un commit par tâche, `ruff`/`pytest` après chaque tâche, jamais de
vérité terrain ni de grille détaillée rédigée pour NIS2/DORA/AI Act).

---

## Tâche 0 — État des lieux

**Commit** `e7a3bac`. Fichier livré : [ETAT_DES_LIEUX.md](ETAT_DES_LIEUX.md)
(chiffres d'origine, avant les tâches suivantes).

## Tâche 1 — Méthode de recherche configurable, lexicale par défaut

**Commits** `cd5e758`, `86cdd49`.

- Fichiers modifiés : `backend/app/core/config.py`, `backend/app/services/rag.py`,
  `backend/app/models/audit.py`, `backend/app/models/framework.py`,
  `render.yaml`, `docs/architecture.md` (DA-07).
- Migrations : `0013_recherche_lexicale` (tentative initiale, recherche plein
  texte PostgreSQL) puis `0014_retrait_tsv` (retour en arrière au profit d'une
  copie Python fidèle de l'algorithme mesuré — voir le commit `86cdd49` pour la
  justification complète).
- Tests ajoutés : `backend/tests/test_rag_retrievers.py` (9 tests — isolation
  multi-organisation et multi-campagne dans les trois modes, classement
  lexical, dédoublonnage hybride, configuration invalide refusée).
- `RAG_RETRIEVER=lexical` par défaut, explicite dans `render.yaml`.

## Tâche 2 — Vérification de citation et revue humaine

**Commit** `86e9aa4`.

- Fichiers modifiés : `backend/app/models/audit.py`, `backend/app/services/audit_engine.py`,
  `backend/app/schemas/audit.py`, `backend/app/services/reports.py`,
  `frontend/index.html`, `frontend/tests/test_dashboard_and_audit.py`.
- Migration : `0015_finding_verification` (colonnes `verdict`,
  `citation_verified`, `needs_human_review`, `review_reason` sur `findings` ;
  réversible, testée upgrade/downgrade/upgrade).
- Tests ajoutés : `backend/tests/test_finding_verification.py` (10 tests — règle
  pure `_verification_humaine` + chaîne complète via mock de `llm.complete_json`) ;
  1 test Playwright (badge « Revue humaine requise »).

## Tâche 3 — Métriques d'exécution (mode dégradé, appels, jetons)

**Commit** `b863c22`.

- Fichiers modifiés : `backend/app/services/llm.py`, `backend/app/services/audit_engine.py`,
  `backend/app/models/audit.py`, `backend/app/schemas/audit.py`,
  `backend/app/core/config.py`, `frontend/index.html`.
- Migration : `0016_audit_run_metrics` (colonnes `degraded`, `llm_fallbacks`,
  `llm_calls`, `llm_prompt_tokens`, `llm_completion_tokens`, `llm_model`,
  `retriever`, `duration_seconds` sur `audits` ; réversible, testée).
- Nouveau script : `backend/scripts/cout_analyses.py`.
- Tests ajoutés : `backend/tests/test_audit_metrics.py` (2 tests — compteurs
  corrects, mode dégradé forcé).

## Tâche 4 — Stockage persistant sur Render

**Commit** `3f00834`.

- Fichiers modifiés : `render.yaml` (disque 1 Go monté sur `/var/data`,
  `STORAGE_DIR=/var/data/storage`), `backend/app/main.py` (vérification
  d'écriture au démarrage, log clair sans bloquer), `docs/architecture.md`.
- **Non testable localement** — voir « À faire par l'équipe » ci-dessous.

## Tâche 5 — CI alignée avec la documentation

**Commit** `35f047f`.

- `.github/workflows/ci.yml` : `backend-tests` installe `pytest-cov` et exécute
  `pytest -q --cov=app --cov-report=term-missing --cov-fail-under=80` (bloquant) ;
  nouveau job `secrets` (`gitleaks/gitleaks-action@v2`, `fetch-depth: 0`).
- `docs/normes-programmation.md` mis à jour pour refléter exactement ce que la
  CI vérifie et ce qui est bloquant.
- **Scan gitleaks** (vérifié localement avant d'ajouter le job, image Docker
  `zricethezav/gitleaks`, historique complet, 125 commits) : **aucune détection**.
  Confirmé de nouveau par le job `secrets` en CI réelle.

## Tâche 6 — Documentation cohérente avec le code

**Commit** `ece3333`.

- `docs/architecture.md` : team-size wording corrigé (5 personnes), DA-03
  précisée (isolation applicative testée, RLS « prévue, non activée » avec la
  raison concrète).
- `backend/app/services/embeddings.py` : docstring déjà exacte, vérifiée sans
  changement nécessaire.
- `README.md` : chiffres réels (181 tests backend, 23 frontend, 23
  garde-fous, couverture 80 % bloquante) ; phrase sur le choix lexical par
  défaut.
- `CHANGELOG.md` : une entrée par tâche (1 à 4).

## Tâche 7 — Préparation de la mesure sur le corpus de 15 documents

**Commit** `377d15e`. Préparation uniquement — **aucune mesure réelle n'a été
lancée** (consommerait ~700 appels Groq pour 3 passages × 15 documents).

- `validation/evaluate.py` : `--corpus`/`--verite` configurables, adaptateur
  vers `corpus/verite_terrain.json`, règle de comparaison des groupes
  d'articles (« 15-22 », « 44-49 ») fixée et documentée **avant** toute
  mesure, extraction d'effectif depuis la description du cas, intervalle de
  confiance de Wilson, métriques d'exécution de la Tâche 3 dans le rapport
  JSON.
- Vérifié en local avec `--sans-modele` (1 document, heuristique) : le script
  tourne de bout en bout sans erreur. Résultat non valide pour le mémoire,
  uniquement une preuve que le script fonctionne.

## Tâche 8 — Profil de l'organisation pour le filtre d'éligibilité

**Commit** `b7ce7c7`.

- Fichiers modifiés : `backend/app/models/organization.py`,
  `backend/app/schemas/organization.py`, `backend/app/api/v1/organizations.py`,
  `frontend/index.html`.
- Migration : `0017_profil_organisation` (11 colonnes `Boolean` nullable sur
  `organizations`, les mêmes que celles lues par
  `eligibilite.py::depuis_organisation` — vérifiées dans le fichier, pas
  seulement supposées ; réversible, testée).
- `PATCH /orgs/{org_id}/profile` (admin et au-dessus), sémantique
  `exclude_unset` : un champ omis reste inchangé, envoyé à `null` il repasse
  explicitement à « non renseigné ».
- Frontend : formulaire « Profil de l'organisation » dans les paramètres du
  compte (Oui / Non / Je ne sais pas par question, avec une phrase d'aide) ;
  vérifié visuellement (Playwright, capture d'écran) avec un aller-retour
  complet enregistrement → rechargement → persistance.
- Tests ajoutés : `backend/tests/test_organization_profile.py` (4 tests —
  permissions, sémantique `exclude_unset`, un profil complet de petite
  structure exempte l'article 30 avec justification citant l'art. 30(5), un
  profil inconnu laisse l'article suivre l'évaluation normale).

## Tâche 9 — Comparaison de deux campagnes

**Commit** `823a929`.

- Fichiers modifiés : `backend/app/api/v1/audits.py`,
  `backend/app/schemas/audit.py`, `frontend/index.html`.
- Nouveau fichier : `backend/app/services/comparison.py`.
- `GET /orgs/{org_id}/audits/{audit_id}/compare?with={other_id}` : compare les
  constats dans le périmètre (hors non-applicable) de deux campagnes du même
  référentiel, catégorise chaque article (nouveau, résolu, inchangé, aggravé,
  amélioré) et calcule le delta de score. Refuse entre deux organisations
  (404, via le filtrage déjà en place) ou deux référentiels différents (409).
- Frontend : bouton « Comparer avec… » depuis une campagne terminée, nouvelle
  vue `#/comparer/{id}` ; vérifié visuellement (Playwright, capture d'écran)
  avec deux campagnes réelles.
- Tests ajoutés : `backend/tests/test_comparison.py` (3 tests — les cinq
  catégories, refus inter-organisations, refus inter-référentiels).

## Corrections hors plan de tâches

Remontées par l'utilisatrice en cours d'usage réel, traitées au fil de l'eau
entre la Tâche 9 et la Tâche F1 :

- **Commit `4ac1f8a`** — Faux échecs de vérification de citation : le modèle
  recopiait parfois l'étiquette de son propre prompt (`[Extrait N —
  référence]`) dans la citation renvoyée, faisant échouer la comparaison
  littérale ; et une citation authentique assemblée à partir de plusieurs
  phrases réelles non contiguës ne correspondait à aucun passage unique.
  Diagnostiqué avec des appels réels à Groq (clé présente en local), pas
  supposé. 3 tests ajoutés à `backend/tests/test_audit_pipeline.py`.
- **Commit `8b38427`** — Harmonisation visuelle des badges de vérification :
  remplacement d'un système CSS parallèle (`.badge-verif`, collision de
  spécificité avec `.alerte`) par les composants déjà existants (`.etiq`
  frontend, `.badge` + couleurs `SEVERITY_LABEL` dans les rapports).
- **Commit `6f588ec`** — Retrait du panneau « Détails techniques de
  l'analyse » (frontend), à la demande explicite.
- **Commit `562dc30`** — Le filtre de statut du plan de remédiation
  proposait 6 statuts alors que cette page ne charge que les constats
  ouverts/en cours : choisir « Résolu » ou « Risque accepté » affichait
  toujours une liste vide. `barreFiltres()` accepte désormais une liste de
  statuts restreinte au contexte.

## Tâche F1 — Filtre d'éligibilité pour NIS2, DORA et AI Act

**Commit** `a18706f`.

- Étend `eligibilite.py` (Tâche 8, jusqu'ici RGPD uniquement) aux trois
  autres référentiels. Avant d'écrire une règle, relecture du texte intégral
  de chaque article auditable ingéré (pas seulement les titres) : 5
  corrections apportées à la grille proposée par le document de cadrage
  (détaillées et justifiées dans le docstring du module), notamment des
  articles NIS2/DORA plus étroits que leur statut général ne le laisse
  supposer, des articles DORA institutionnels toujours hors périmètre pour
  une organisation cliente, et l'article 5 de l'AI Act jamais exemptable.
- Migration : `0018_profil_referentiels` (5 colonnes nullables sur
  `organizations` : `entite_nis2`, `entite_financiere_dora`,
  `ia_fournisseur_haut_risque`, `ia_deployeur_haut_risque`, `ia_utilisee` ;
  réversible, testée upgrade/downgrade/upgrade).
- `POST /orgs/{org_id}/audits` renvoie désormais `scope_warning` (non
  bloquant) si le profil indique que le référentiel entier ne s'applique
  pas à l'organisation.
- Frontend : formulaire « Profil de l'organisation » restructuré par
  référentiel (RGPD/NIS2/DORA/AI Act) ; vérifié visuellement (Playwright,
  capture d'écran) avec un aller-retour complet enregistrement →
  rechargement → persistance.
- Tests ajoutés : `backend/tests/test_eligibilite_multi_referentiel.py` (18
  tests — chaque règle/correction, `referentiel_hors_champ()`, un test
  d'intégration bout-en-bout avec un connecteur factice prouvant zéro appel
  au modèle sur des articles exemptés) ; `backend/tests/test_eligibilite.py`
  corrigé (un test supposait l'absence de toute règle NIS2, devenue fausse
  une fois la Tâche F1 posée — réécrit pour vérifier la vraie propriété
  visée : l'absence de fuite des règles RGPD vers NIS2).

## Tâche F2 — Préparation de la mesure sur NIS2, DORA et AI Act

**Commit** `01b2569`. Préparation uniquement — **aucune vérité terrain
rédigée, aucune mesure réelle lancée** (interdit par le document de
cadrage).

- `validation/evaluate.py --referentiel {rgpd,nis2,dora,ai_act}` : fixe les
  valeurs par défaut de `--corpus`/`--verite` selon le référentiel, sans
  rien changer au comportement RGPD existant (défauts historiques
  inchangés tant que `--corpus`/`--verite` ne sont pas passés
  explicitement).
- Nouveau `validation/verifier_verite_terrain.py` : vérifie la structure
  d'un fichier de vérité terrain (clés d'article valides, vocabulaire des
  verdicts, cohérence de `jamais_exclure`, fichiers présents dans le
  corpus) — jamais le contenu sur le fond. Vérifié à la fois sur un cas
  volontairement cassé (erreurs bien détectées) et sur le vrai corpus RGPD
  de 210 verdicts (aucun faux positif).
- Dossiers `corpus_nis2/`, `corpus_dora/`, `corpus_ai_act/` créés à la
  racine (squelettes vides + `README.md` par référentiel expliquant le
  format et les particularités de son filtre d'éligibilité) : composer les
  documents et leur vérité terrain reste le travail de l'équipe.
- Pipeline `--referentiel` vérifié de bout en bout avec un document et une
  vérité terrain jetables, non commités (confirme que le Framework, le
  filtrage par article et la comparaison à la vérité terrain fonctionnent
  réellement pour un référentiel non-RGPD) avant d'écrire cette tâche comme
  terminée.

## Tâche F3 — Documentation

Ce document, plus `README.md` (nombre de tests à jour, mention de
`--referentiel`), `CHANGELOG.md` (une entrée par commit depuis la Tâche 9)
et `docs/architecture.md` (DA-08, ligne « Mesure de précision hors RGPD »
dans les points de vigilance connus).

---

## Chiffres à reporter dans le mémoire

| Métrique | Valeur |
|---|---|
| Tests backend | 209 (`backend/tests`, `pytest`) |
| Tests frontend bout-en-bout | 23 (`frontend/tests`, Playwright) |
| Tests garde-fous du moteur | 23 (`validation/test_garde_fous.py`) |
| Couverture de tests backend | ~81,3 % (bloquant en CI, `--cov-fail-under=80`) |
| Méthode de recherche par défaut | Lexicale (`RAG_RETRIEVER=lexical`) — voir `validation/comparaison_retrievers.json` et DA-07 |
| Champs affichés par constat | `verdict`, `citation_verified` (badge « Citation vérifiée ✓ » / « Citation non retrouvée »), `needs_human_review` (badge « Revue humaine requise », motif en infobulle), `review_reason` |
| Secrets détectés dans l'historique | 0 (gitleaks, scanné à chaque push) |
| Profil d'organisation | 16 champs (`PATCH /orgs/{id}/profile`), tous nullable, jamais convertis en False — 11 RGPD (Tâche 8) + 5 NIS2/DORA/AI Act (Tâche F1) |
| Règles d'éligibilité | RGPD (Tâche 8) + ~40 nouvelles pour NIS2/DORA/AI Act (Tâche F1) |
| Corpus de validation mesuré | RGPD uniquement (15 documents, 210 verdicts) ; NIS2/DORA/AI Act : squelettes prêts, composition par l'équipe (Tâche F2) |

---

## Ce que l'équipe doit faire elle-même

1. **Tarifs Groq** — remplir `LLM_PRICE_INPUT_PER_MTOK_USD` et
   `LLM_PRICE_OUTPUT_PER_MTOK_USD` dans `backend/app/core/config.py` depuis la
   page tarifaire officielle de Groq pour le modèle utilisé (`GROQ_MODEL`).
   Actuellement à `0.0`, `estimated_llm_cost_usd` reste `None` tant que ce
   n'est pas fait — jamais de tarif inventé.
2. **Déployer sur Render, puis vérifier le disque persistant** (Tâche 4) :
   après déploiement, déposer un document de test, redémarrer le service
   `complianceai-api` depuis le tableau de bord Render, confirmer que le
   document est toujours présent. Non testable localement (pas de disque
   Render en local).
3. **Lancer la mesure de la Tâche 7 avec la clé Groq réelle**, en ayant
   budgété le quota (~700 appels pour 3 passages × 15 documents) :
   ```
   python -m validation.evaluate --corpus corpus \
       --verite corpus/verite_terrain.json --runs 3 --output rapport.json
   ```
   (depuis la racine du dépôt, avec `PYTHONPATH=backend` et `DATABASE_URL`/
   `JWT_SECRET`/`GROQ_API_KEY` renseignés — voir `backend/.env` pour le
   gabarit). Ne jamais ajuster la règle de comparaison des groupes d'articles
   après avoir vu les résultats (documentée dans le docstring de
   `validation/evaluate.py`).
4. **Lancer `backend/scripts/cout_analyses.py`** sur la base de production,
   après quelques analyses réelles :
   ```
   python -m scripts.cout_analyses
   ```
   (depuis `backend/`, avec `DATABASE_URL` pointant vers la base de
   production).
5. **Revoyer les secrets détectés par gitleaks** — aucun trouvé lors du scan
   du 2026-09-24, mais le job `secrets` tourne désormais sur chaque push :
   traiter toute détection future en revoquant la clé concernée, jamais en
   réécrivant l'historique.
6. **Chronométrer une analyse RGPD de `corpus_demo/03_intermediaire.txt` sur
   l'application déployée.** Si l'analyse dépasse 60 secondes, préparer une
   campagne déjà analysée pour la démonstration plutôt que de lancer
   l'analyse en direct devant le jury.
7. **Composer les corpus NIS2/DORA/AI Act** (Tâche F2) — documents `.txt` et
   vérité terrain article par article dans `corpus_nis2/`, `corpus_dora/`,
   `corpus_ai_act/` (voir le `README.md` de chaque dossier pour le format et
   les particularités du filtre d'éligibilité de ce référentiel). Vérifier
   la structure avant toute mesure :
   ```
   python -m validation.verifier_verite_terrain --referentiel nis2
   ```
   puis lancer la mesure réelle (même avertissement de quota Groq que la
   Tâche 7) :
   ```
   python -m validation.evaluate --referentiel nis2 --runs 3 --output rapport_nis2.json
   ```
   Ne jamais ajuster une règle d'éligibilité ou de comparaison après avoir
   vu les résultats.

## Ce qui reste volontairement hors périmètre

RLS (Row Level Security), le moteur `evaluation/` câblé en production,
l'analyse en arrière-plan (file de tâches), le stockage S3, le SSO, d'autres
grilles de validation au-delà du RGPD. Chacun documenté comme « prévu, non
engagé » dans `docs/architecture.md` §6, pas comme un oubli.

## État final

Les dix tâches du plan initial (0 à 9), les quatre corrections hors plan
remontées en usage réel, et les tâches F1 à F3 du second document de
cadrage sont traitées, committées et vérifiées vertes en CI. Rien n'a été
volontairement laissé de côté à ce stade — les seuls éléments restants sont
les actions que seule l'équipe peut accomplir elle-même (voir la section
ci-dessus : tarifs Groq, vérification du disque Render, mesure réelle de la
Tâche 7, `cout_analyses.py` sur la production, composition des corpus
NIS2/DORA/AI Act et leur mesure réelle pour la Tâche F2).
