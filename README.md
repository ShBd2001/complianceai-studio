# ComplianceAI Studio

SaaS multi-tenant d'aide à l'audit de conformité réglementaire (RGPD, NIS2,
DORA, AI Act). Chaque non-conformité doit citer une preuve extraite du
document analysé, et le code — pas le modèle — vérifie mécaniquement que
cette citation existe vraiment dans le texte source. Sans preuve vérifiable,
pas de verdict de conformité.

**Application en ligne** : https://complianceai-web.onrender.com

> Ce n'est pas un outil de certification. Il analyse les documents fournis et
> signale les points qui appellent une attention humaine — voir
> [MENTIONS.md](MENTIONS.md) pour le cadre exact de ce que l'outil affirme et
> n'affirme jamais.

## Ce que couvre l'outil

| Fonction | Détail |
|---|---|
| Comptes et organisations | Multi-tenant, rôles owner / admin / auditeur / lecteur |
| Campagnes d'audit | RGPD, NIS2, DORA, AI Act — dépôt de documents, analyse, constats |
| Vérification par citation | Chaque constat cite un passage réel du document ; le code vérifie que la citation existe |
| Rapports | PDF/HTML versionnés, historique complet par campagne |
| Correspondances entre référentiels | Rapprochements indicatifs entre obligations de deux référentiels |
| Plan de remédiation | Agrégation des non-conformités ouvertes, toutes campagnes confondues |
| Journal d'activité | Append-only, aucune route de modification ni de suppression |
| Droits RGPD sur l'outil lui-même | Export et suppression des données personnelles |
| Veille réglementaire | Ré-ingestion périodique des textes sources, notification si le texte change réellement |
| Offres et quotas | Essentiel / Pro / Cabinet, campagnes par mois et utilisateurs appliqués côté serveur |

## Architecture en bref

```
Frontend   SPA JavaScript natif, un seul fichier statique (frontend/)
Backend    FastAPI, monolithe modulaire en couches (backend/app/)
Données    PostgreSQL 16 + pgvector (relationnel et vectoriel dans la même base)
Modèle     Groq API, appelé une fois par exigence auditable
```

Le détail des décisions d'architecture (pourquoi PostgreSQL plutôt que
ChromaDB, pourquoi un frontend sans framework, comment fonctionne
l'authentification, le multi-tenant, la traçabilité des décisions du
modèle...) est dans [docs/architecture.md](docs/architecture.md).

## Démarrage rapide

Deux terminaux, une fois PostgreSQL démarré (`docker compose up -d` dans
`backend/`) :

```bash
# Terminal 1 — API
cd backend
pip install -r requirements.txt
alembic upgrade head
python -m app.ingestion.cli          # ingère RGPD, NIS2, DORA, AI Act
uvicorn app.main:app --reload --port 8000

# Terminal 2 — interface
cd frontend
python -m http.server 5173
```

Ouvrir http://localhost:5173. Procédure complète, dépannage inclus :
[INSTALLATION.md](INSTALLATION.md).

## Comment la précision du moteur est mesurée

`validation/` est un harnais indépendant du backend : il rejoue l'extraction
et la vérification de citations sur un corpus de documents dont la
conformité est connue à l'avance ([CORPUS.md](CORPUS.md)), et mesure
précision, rappel et intervalle de confiance par rapport à cette vérité
terrain. C'est ce qui a servi à valider — puis à corriger — la méthode avant
son intégration dans le moteur de production (`backend/app/services/audit_engine.py`) :
voir [CHANGELOG.md](CHANGELOG.md) pour un exemple de diagnostic et correction
mesurés (articles 30 et 37).

```bash
python -m validation.test_garde_fous                          # 23 tests de sûreté, sans appel API
python -m validation.run_validation --corpus corpus_demo \
       --verite corpus_demo/verite_terrain.json --hors-ligne   # plancher heuristique, sans LLM
```

Détail des métriques et du corpus : [validation/README.md](validation/README.md).

`validation/evaluate.py --referentiel {rgpd,nis2,dora,ai_act}` mesure le
moteur de production sur un référentiel donné (défaut RGPD, inchangé). Seul
le RGPD dispose aujourd'hui d'un corpus mesuré ; `corpus_nis2/`,
`corpus_dora/`, `corpus_ai_act/` sont des squelettes prêts à l'emploi
(README + `python -m validation.verifier_verite_terrain`) pour l'équipe.

## Tests et intégration continue

- **Backend** : 209 tests (`backend/tests`, `pytest`) — authentification,
  isolation multi-tenant, pipeline d'audit complet, quotas, veille
  réglementaire, RGPD, filtre d'éligibilité RGPD/NIS2/DORA/AI Act.
  Couverture globale 80 % (`--cov-fail-under=80`, bloquant en CI).
- **Frontend** : 23 tests bout-en-bout (`frontend/tests`, Playwright) — un
  vrai navigateur pilote la vraie interface contre un vrai backend, aucun
  mock du DOM.
- **Garde-fous du moteur** : 23 tests (`validation/test_garde_fous.py`,
  sans appel API, exécutés sur chaque commit).

La recherche des passages pertinents (`app/services/rag.py`) est lexicale
par défaut (`RAG_RETRIEVER=lexical`) : mesuré sur le corpus de validation,
le lexical seul bat le sémantique seul sur toutes les métriques — voir
[validation/comparaison_retrievers.json](validation/comparaison_retrievers.json)
et DA-07 dans [docs/architecture.md](docs/architecture.md).
- **CI** (`.github/workflows/ci.yml`) : garde-fous du moteur (sans quota),
  suite backend, suite bout-en-bout, lint (`ruff`), audit de dépendances
  (`pip-audit`, non bloquant), et — sur `main` uniquement, car consommateur
  de quota Groq — une validation non-régression avec seuils bloquants sur le
  corpus réel.

## Limites connues

Documentées volontairement plutôt que découvertes en soutenance — voir la
section « Points de vigilance connus » de
[docs/architecture.md](docs/architecture.md#6-points-de-vigilance-connus).

## Autres documents

| Document | Contenu |
|---|---|
| [docs/architecture.md](docs/architecture.md) | Décisions d'architecture, vue de déploiement, limites connues |
| [INSTALLATION.md](INSTALLATION.md) | Installation pas à pas, machine vierge à suite de tests au vert |
| [MENTIONS.md](MENTIONS.md) | Ce que l'outil affirme, n'affirme jamais, et pourquoi |
| [CORPUS.md](CORPUS.md) | Le corpus de validation, document par document |
| [CHANGELOG.md](CHANGELOG.md) | Diagnostics et corrections de précision du moteur |
| [validation/README.md](validation/README.md) | Méthodologie de mesure (précision, rappel, intervalle de confiance) |
| [frontend/README.md](frontend/README.md) | Démarrage et conventions du frontend |
