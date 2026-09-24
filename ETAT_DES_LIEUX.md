# État des lieux — avant travaux de pré-soutenance

Mesuré le 2026-09-24, sur la base locale (PostgreSQL + pgvector), avant toute
tâche du cahier des charges de pré-soutenance. Sert de référence aux chiffres
cités dans le mémoire et dans `CHANGEMENTS_SOUTENANCE.md`.

## Résultat de la suite backend

```
cd backend && pytest -q
```

**173 tests, 100 % de réussite, aucun échec.**

## Nombre de tests par catégorie

| Catégorie | Commande | Nombre |
|---|---|---|
| Backend (`backend/tests/`) | `pytest --collect-only -q` dans `backend/` | **173** |
| Frontend bout-en-bout (`frontend/tests/`) | `pytest --collect-only -q frontend/tests` | **23** |
| Garde-fous du harnais de validation | `python -m validation.test_garde_fous` | **23** |
| **Total** | | **219** |

### Détail backend, par fichier

| Fichier | Tests |
|---|---|
| `test_audit_pipeline.py` | 28 |
| `test_auth_flow.py` | 28 |
| `test_crosswalks.py` | 3 |
| `test_eligibilite.py` | 29 |
| `test_email.py` | 13 |
| `test_notifications.py` | 7 |
| `test_rag.py` | 13 |
| `test_regulatory_watch.py` | 4 |
| `test_retention.py` | 7 |
| `test_scheduler_loop.py` | 4 |
| `test_scheduling.py` | 10 |
| `test_scoping.py` | 27 |
| **Total** | **173** |

## Couverture (`pytest --cov=app --cov-report=term`)

**80 % au global** (2 987 instructions, 595 non couvertes).

| Module | Couverture | Note |
|---|---|---|
| `app/services/llm.py` | 34 % | Le client Groq lui-même : les tests mockent `complete_json`, le code d'appel réseau réel (gestion des erreurs HTTP, réessais) n'est pas exercé. |
| `app/services/pdf.py` | 40 % | Génération PDF (Playwright headless) : peu exercée en tests unitaires, couverte indirectement par les tests bout-en-bout frontend. |
| `app/ingestion/eurlex.py` | 0 % | Connecteur EUR-Lex réel : les tests d'ingestion utilisent `FakeConnector`, jamais le vrai réseau (principe déjà documenté ailleurs : un test ne doit pas dépendre d'un service externe). |
| `app/ingestion/csrd_consolide.py` | 0 % | Idem, connecteur CSRD réel. |
| `app/ingestion/eurlex.py`, `crosswalks.py`, `cli.py` | 0 % | Scripts d'ingestion à usage ponctuel (CLI), pas de test dédié. |
| `app/services/documents.py` | 66 % | Extraction de texte (PDF/DOCX) : les chemins d'erreur (fichier corrompu) sont peu couverts. |
| `app/services/embeddings.py` | 73 % | Le chemin `FastEmbedEmbedder` réel n'est pas exercé (tests en `EMBEDDING_BACKEND=hashing`, voir `conftest.py`). |
| `app/api/v1/organizations.py` | 77 % | |
| `app/main.py` | 77 % | |
| Reste des modules `app/models/`, `app/schemas/`, `app/services/rag.py`, `app/services/audit_engine.py` | 89–100 % | |

Les zéros ne sont pas des trous de test : ce sont des chemins qui, par
construction, ne doivent jamais s'exécuter dans la suite (accès réseau réel
à un service externe, scripts CLI d'exploitation). Voir
`backend/tests/conftest.py`, qui désactive explicitement le LLM
(`LLM_ENABLED=false`, `GROQ_API_KEY=""`) et bascule les embeddings sur le
repli déterministe (`EMBEDDING_BACKEND=hashing`) pour cette raison précise.

## Méthode de mesure

```bash
cd backend
pytest -q                                        # resultat global
pytest --collect-only -q                         # compte des tests backend
pytest --cov=app --cov-report=term               # couverture
cd ..
pytest --collect-only -q frontend/tests          # compte des tests frontend
python -m validation.test_garde_fous             # garde-fous du harnais
```

Base de test dédiée (`..._test`), créée et migrée automatiquement par
`backend/tests/conftest.py` — jamais la base de développement.
