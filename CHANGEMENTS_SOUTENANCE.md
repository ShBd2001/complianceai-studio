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

## Tâche F2 — Mesure réelle sur NIS2, DORA et AI Act

**Préparation** : commit `01b2569` (harnais `--referentiel`,
`validation/verifier_verite_terrain.py`, dossiers `corpus_nis2/`,
`corpus_dora/`, `corpus_ai_act/` créés vides).

**Corpus et mesure** : protocole en plusieurs étapes avec point de contrôle
explicite fourni par l'équipe — brouillon rédigé par Claude Code à la
demande de l'équipe (4 documents fictifs + vérité terrain par référentiel,
219 verdicts annotés au total), relu et corrigé par l'équipe, gelé
(`c3bbdc1`, « corpus NIS2/DORA/AI Act validés par l'équipe ») seulement
après le mot « référence validée ». Aucune vérité terrain n'a été rédigée
puis mesurée sans ce passage par l'équipe.

- Bloc `profil` structuré ajouté au format de `verite_terrain.json`
  (`entite_nis2`, `entite_financiere_dora`, `ia_fournisseur_haut_risque`,
  `ia_deployeur_haut_risque`, `ia_utilisee`), appliqué directement à
  l'organisation de test par `validation/evaluate.py::_appliquer_profil` et
  validé par `verifier_verite_terrain.py` — plus fiable que l'extraction
  heuristique depuis `description`, seule disponible jusqu'ici pour
  l'effectif RGPD.
- Mesure réelle (3 passages/document, commit `c47b0f6`,
  `mesure_nis2.json`/`mesure_dora.json`/`mesure_ai_act.json`) : exactitude
  90,6 % / 91,4 % / 86,7 %, exclusions abusives 0 / 0 / 1. Rapport complet
  remis à l'équipe avec la liste de toutes les erreurs et une section
  séparée signalant les verdicts attendus que Claude Code considère
  possiblement discutables (référence non modifiée après mesure).
- Deux constats non corrigés avant le gel, faute de temps pour une nouvelle
  mesure de vérification : faux positifs élevés sur les documents conformes
  en DORA/AI Act (précision 77,8 %/52,4 %), et une exclusion abusive isolée
  (AI Act, article 49) — documentés dans `docs/architecture.md` §6.

## Tâche F2 (suite) — Extension du laboratoire à NIS2, DORA et AI Act

À la demande explicite de l'équipe (le document de cadrage limitant
initialement la rédaction de grilles détaillées à une revue préalable a été
levé pour cette extension) : le laboratoire (`evaluation/`), qui ne
couvrait que le RGPD (`referentiel/articles.py` codé en dur), est étendu
aux trois autres référentiels — commits `20109a5` (généralisation +
grilles) et `c7b6abc` (job CI `non-regression`). Réutilise le corpus déjà
gelé de la Tâche F2 (mêmes documents, même vérité terrain), sans le
modifier.

- `evaluation/prompts.py`/`evaluateur.py` généralisés (référentiel en
  paramètre, défaut RGPD) : texte des prompts RGPD vérifié identique
  caractère pour caractère avant tout push, confirmé sans régression en CI
  réelle.
- Trois nouvelles grilles (`referentiel/articles_{nis2,dora,ai_act}.py`).
  Écart assumé et documenté (DA-10) : les 3 articles institutionnels de
  DORA (15/20/21) sont absents de la grille du laboratoire, qui n'a pas de
  mécanisme d'exemption indépendant du contenu du document.
- Deux bugs trouvés et corrigés pendant la construction (mesure réelle,
  pas en relisant le code) : une condition d'applicabilité mal configurée
  provoquait 8 exclusions abusives sur l'AI Act ; corrigées, ramenées à 0.
- Mesure réelle finale : exactitude 90,6 % (NIS2), ~88 % corrigé / 76,6 %
  brut (DORA, sous-compté par les 3 absences volontaires), 92,9 % (AI Act,
  0 exclusion abusive, rappel 100 %).
- Job CI `non-regression` mesure désormais les 4 référentiels à chaque
  push sur `main` (timeout porté de 25 à 45 minutes).

## Tâche F2 (suite) — Correction post-gel de 2 verdicts NIS2

À la demande explicite de l'équipe, après relecture du rapport F2 initial :
2 des 3 faux négatifs NIS2 (rappel initial 72,7 %) provenaient de verdicts
attendus déjà signalés comme discutables dans ce même rapport — article 24
(doc 2, obligation facultative pour l'État membre) et article 30 (doc 3,
notification purement volontaire). Corrigés avec justification dans
`corpus_nis2/verite_terrain.json`, puis remesurés sur les deux moteurs.
Résultat production : **exactitude 100 %, rappel 100 %, 0 faux négatif**
(`mesure_nis2.json` mis à jour). L'article 21 (doc 3), également signalé
comme débattable, n'a volontairement pas été corrigé — les gaps
structurels identifiés y restent réels.

## Tâche F2 (suite) — AI Act art. 49 : investigué comme un bug, corrigé comme une vérité terrain

L'exclusion abusive du rapport F2 (article 49, doc 2, « la seule des trois
référentiels ») a d'abord été traitée comme un défaut du moteur : un
correctif de `SYSTEM_PROMPT` a été écrit puis testé en conditions réelles
(3 exécutions du document concerné) — **aucun effet mesuré**, verdict
stable à l'identique, correctif abandonné et retiré. Lire le raisonnement
réel du modèle en base (`Finding.description`, pas une supposition) a
montré une lecture juridique précise et cohérente, déjà identifiée comme
zone grise dans le rapport F2 initial (l'article 49§3 vise en particulier
les déployeurs publics ; cette entreprise est privée) : ce n'était pas un
bug du moteur, c'était la vérité terrain qui tranchait à tort une question
réellement ambiguë. Corrigée (`manquement` → `tolere`) à la demande
explicite de l'équipe. Résultat production : **exactitude 86,7 % → 92,8 %,
rappel 84,6 % → 91,7 %, exclusions abusives 1 → 0** (`mesure_ai_act.json`
mis à jour). Aucun changement de code n'a finalement été nécessaire.

## Tâche F2 (suite) — RGPD : première mesure réelle du moteur de production

La Tâche 7 avait préparé le script mais reporté la mesure réelle faute de
budget Groq (commit `d090150`, 24/09 — item 3 de la liste "Ce que l'équipe
doit faire elle-même" ci-dessous, maintenant fait). Exécutée le 2026-09-28
(`python -m validation.evaluate --referentiel rgpd --corpus corpus --verite
corpus/verite_terrain.json --runs 3 --output mesure_rgpd.json`) :
**exactitude 66,2 %, précision 55,6 %, rappel 76,9 %** — nettement sous
NIS2/DORA/AI Act (91-100 %) et sous le laboratoire RGPD.

Cause identifiée par lecture du code (`audit_engine.py::run_audit`, phase 1) :
la requête envoyée pour chercher les passages pertinents dans le document
client est `f"{requirement.title} {requirement.body[:300]}"` — le texte
légal brut de l'article. Le laboratoire construit la sienne à partir des
`indices` de `referentiel/articles.py`, des mots-clés écrits à la main pour
matcher le vocabulaire d'un vrai document. Sur les articles au libellé le
plus abstrait (12, 13, 15-22, 32-34, 44-49), le recouvrement lexical est nul
dans la plupart des documents — y compris ceux conçus comme conformes — et
le retriever lexical retombe sur les premiers passages du document dans
leur ordre d'origine, sans rapport avec la question. Confirmé par les
verdicts eux-mêmes : faux positifs "manquement" à haute confiance
(0,7-0,9), donc sans déclencher le second avis DA-09 — un problème de
recherche de passages, pas de vote.

Plusieurs correctifs testés en conditions réelles. Deux premiers essais sur
un sous-corpus de 4 documents (01, 02, 09, 12), sans effet net : repli
sémantique si le score lexical est nul (66,1 % → 67,9 %) et requête réduite
au titre seul (64,3 %, pire). Troisième, la bonne piste : réutiliser les
`indices` BLOQUANTS déjà écrits à la main dans les 4 grilles du laboratoire
(DA-10), copiés statiquement dans `app/ingestion/mots_cles_recherche.py`,
RGPD uniquement (dégrade NIS2/DORA/AI Act, déjà à 91-100 %, vérifié
séparément). Un premier essai (mots-clés concaténés à la requête, décodés
mot par mot) a introduit deux exclusions abusives successives sur des mots
génériques isolés ("direction", puis "prestataire") — corrigé à la racine
par `rag.py::_scores_phrases` : appariement par phrase ENTIÈRE, bonus
seulement si au moins 2 phrases distinctes matchent.

Mesuré sur le corpus complet (15 documents, 210 verdicts, 3 passages,
`mesure_rgpd.json`) : **exactitude 66,2 % → 76,7 %, précision 55,6 % →
68,5 %, rappel 76,9 % → 80,8 %, exclusions abusives 0** — stable sur
plusieurs tirages de vérification. Déployé (commits `ccc9f6e`, `3e793b3`).
`--ci` de `validation/evaluate.py` toujours pas étendu à RGPD, à
reconsidérer une fois ce chiffre confirmé stable sur d'autres mesures.
Documenté dans `CHANGELOG.md`, `docs/architecture.md` §6, `CORPUS.md` et
`README.md`.

Reste sous le laboratoire (84-87 % sur ce même corpus). Différence
structurelle : le laboratoire extrait une preuve par élément de la grille
et laisse le CODE décider du verdict ; la production demande un verdict
holistique directement au modèle. Prototype tenté pour rapprocher les deux
(`app/ingestion/grille_rgpd.py`, `audit_engine.py::_evaluer_par_elements`,
RGPD uniquement) puis abandonné le même jour : mesuré à 67,2 % sur le même
sous-corpus, moins bon que l'approche mots-clés déjà déployée
(75,9-81,0 %) — exiger une citation exacte par élément s'est révélé trop
strict (le document de référence 01 s'effondre à 38,8 au lieu de 88-100).
Non déployé, code retiré. Voir CHANGELOG.md pour le détail de la mesure et
la piste à reprendre (séparer l'appel applicabilité des éléments, comme le
fait réellement le laboratoire).

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
| Corpus de validation mesuré | RGPD (15 documents, 210 verdicts) + NIS2/DORA/AI Act (4 documents chacun, 219 verdicts au total) — mesuré sur les deux moteurs (production, Tâche F2 ; laboratoire, DA-10) |

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
3. ~~**Lancer la mesure de la Tâche 7 avec la clé Groq réelle**~~ — fait le
   2026-09-28 (`mesure_rgpd.json`) : exactitude 66,2 % initialement,
   corrigée le même jour à **76,7 %** (mots-clés du laboratoire). Voir la
   section « Tâche F2 (suite) — RGPD » ci-dessus pour le diagnostic complet.
   Un prototype "preuve par élément" (rapprochement avec le laboratoire,
   84-87 % sur ce corpus) a été tenté et mesuré à 67,2 % sur un sous-corpus
   — moins bon, non déployé. **Reste à faire par l'équipe** : reprendre
   cette piste en séparant l'appel applicabilité des éléments comme le fait
   réellement le laboratoire (le prototype abandonné faisait les deux en un
   seul appel).
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
7. **Arbitrer le constat restant de la Tâche F2** (voir `docs/architecture.md`
   §6) : faux positifs sur les documents conformes en DORA (précision
   77,8 %) et AI Act (précision 64,7 %) — le moteur exige un niveau de
   détail assez fin avant d'accepter "conforme". Décider si et comment
   `audit_engine.py` doit être retouché après la soutenance, avec une
   nouvelle mesure de vérification avant tout gel définitif du correctif.
   (L'exclusion abusive AI Act art. 49, initialement dans cette liste, est
   résolue — voir la section « AI Act art. 49 » ci-dessus : ce n'était pas
   un bug du moteur, la référence a été corrigée à sa place.)

## Ce qui reste volontairement hors périmètre

RLS (Row Level Security), le moteur `evaluation/` câblé en production,
l'analyse en arrière-plan (file de tâches), le stockage S3, le SSO, d'autres
grilles de validation au-delà du RGPD. Chacun documenté comme « prévu, non
engagé » dans `docs/architecture.md` §6, pas comme un oubli.

## État final

Les dix tâches du plan initial (0 à 9), les quatre corrections hors plan
remontées en usage réel, et les tâches F1 à F3 du second document de
cadrage — y compris la composition du corpus, la mesure réelle NIS2/DORA/
AI Act de la Tâche F2 sur le moteur de production, et son extension au
laboratoire (DA-10, à la demande explicite de l'équipe) — sont traitées,
committées et vérifiées vertes en CI, les quatre référentiels protégés en
continu sur les deux moteurs. Rien n'a été volontairement laissé de côté à
ce stade — les seuls éléments restants sont les actions que seule l'équipe
peut accomplir elle-même (voir la section ci-dessus : tarifs Groq,
vérification du disque Render, mesure réelle de la Tâche 7,
`cout_analyses.py` sur la production, et l'arbitrage des constats F2 non
corrigés avant le gel).
