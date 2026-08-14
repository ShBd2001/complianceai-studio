# Installation pas à pas — ComplianceAI Studio v2

Objectif : partir d'une machine vierge et arriver à l'API qui tourne, la base
remplie, les 30 tests au vert et les référentiels ingérés.

Compter 45 minutes la première fois.

---

## Étape 0 — Logiciels à installer

| Logiciel | Version | Obligatoire | Lien |
|---|---|---|---|
| Python | 3.12 ou 3.13 | oui | https://www.python.org/downloads/ |
| Docker Desktop | dernière | oui | https://www.docker.com/products/docker-desktop/ |
| Git | dernière | oui | https://git-scm.com/downloads |
| VS Code | dernière | recommandé | https://code.visualstudio.com/ |
| Node.js | 20 LTS | plus tard (frontend) | https://nodejs.org/ |

**Windows — coche « Add python.exe to PATH » pendant l'installation de Python.**
C'est la case que tout le monde oublie, et elle fait échouer toutes les
commandes suivantes sans expliquer pourquoi.

**Docker Desktop sur Windows** demande WSL2. L'installeur le propose, accepte.
Redémarrage probable.

Extensions VS Code utiles : `ms-python.python`, `ms-python.vscode-pylance`,
`charliermarsh.ruff`, `ms-azuretools.vscode-docker`.

### Vérification

Ouvre un terminal — PowerShell sur Windows, Terminal sur macOS :

```bash
python --version      # attendu : Python 3.12.x ou 3.13.x
docker --version      # attendu : Docker version 27.x ou plus
git --version
```

Si `python` n'est pas reconnu sur Windows, essaie `py --version`. Si ça marche,
utilise `py` partout à la place de `python` dans la suite.

---

## Étape 1 — Placer le projet

Décompresse `complianceai-v2.zip` où tu veux travailler, puis :

```bash
cd chemin/vers/complianceai-v2
```

Structure attendue :

```
complianceai-v2/
├── README.md
├── INSTALLATION.md
├── docs/
│   ├── architecture.md
│   └── normes-programmation.md
└── backend/
    ├── app/
    ├── alembic/
    ├── tests/
    ├── requirements.txt
    ├── docker-compose.yml
    └── .env.example
```

---

## Étape 2 — Environnement virtuel

Depuis `complianceai-v2` :

```bash
cd backend
python -m venv .venv
```

Activation — **à refaire dans chaque nouveau terminal** :

```powershell
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
```

```bash
# macOS / Linux
source .venv/bin/activate
```

Le prompt doit maintenant commencer par `(.venv)`.

> **Erreur « l'exécution de scripts est désactivée sur ce système »** :
> lance une fois `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`,
> réponds `O`, puis réessaie.

---

## Étape 3 — Dépendances Python

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

Trois à cinq minutes — `fastembed` embarque un moteur ONNX, c'est le plus gros
du téléchargement.

Vérification :

```bash
pip list | findstr /i fastapi     # Windows
pip list | grep -i fastapi        # macOS/Linux
```

> **Derrière un proxy d'entreprise**, `pip` échoue en SSL ou en timeout :
> ```bash
> pip install --proxy http://user:motdepasse@proxy.entreprise.fr:8080 -r requirements.txt
> ```

---

## Étape 4 — Fichier de configuration

```bash
copy .env.example .env     # Windows
cp .env.example .env       # macOS/Linux
```

Génère une clé de signature :

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Ouvre `.env`, remplace `JWT_SECRET=CHANGE_ME` par la valeur affichée. Le fichier
doit ressembler à ceci :

```ini
APP_NAME="ComplianceAI Studio"
ENV=development
DEBUG=true

DATABASE_URL=postgresql+psycopg://compliance:compliance@localhost:5432/complianceai

JWT_SECRET=la_chaine_generee_juste_avant
ACCESS_TOKEN_TTL_MIN=15
REFRESH_TOKEN_TTL_DAYS=14
COOKIE_SECURE=false
COOKIE_DOMAIN=

CORS_ORIGINS=["http://localhost:5173"]

GROQ_API_KEY=
GROQ_MODEL=llama-3.3-70b-versatile
LLM_ENABLED=true

EMBEDDING_BACKEND=fastembed
EMBEDDING_DIM=384

STORAGE_DIR=./storage
MAX_UPLOAD_MB=20
RAG_TOP_K=6
```

`COOKIE_SECURE=false` est correct en local : sans HTTPS, un cookie `Secure` ne
serait jamais transmis par le navigateur.

`GROQ_API_KEY` peut rester vide pour l'instant — le moteur bascule alors sur
une évaluation heuristique et tout reste fonctionnel. Clé gratuite plus tard
sur https://console.groq.com.

`.env` est déjà dans `.gitignore`. **Ne le commite jamais.**

---

## Étape 5 — Démarrer PostgreSQL

Docker Desktop doit être **lancé** (icône baleine, état « Running »), pas
seulement installé.

```bash
docker compose up -d db
```

Premier lancement : téléchargement de l'image `pgvector/pgvector:pg16`.

Vérification :

```bash
docker compose ps
```

Le service `db` doit être `running (healthy)`. S'il est `starting`, attends
dix secondes et relance.

> **« port 5432 already in use »** : un PostgreSQL tourne déjà sur ta machine.
> Soit tu l'arrêtes, soit tu changes le port — dans `docker-compose.yml`
> (`"5433:5432"`) **et** dans `.env` (`...@localhost:5433/complianceai`).

---

## Étape 6 — Créer le schéma

```bash
alembic upgrade head
```

Sortie attendue : trois migrations qui s'enchaînent.

```
Running upgrade  -> 0001_extensions
Running upgrade 0001_extensions -> 0002_schema_initial
Running upgrade 0002_schema_initial -> 0003_referentiels
```

Vérification — **18 tables** doivent exister :

```bash
docker compose exec db psql -U compliance -d complianceai -c "\dt"
```

> **`extension "vector" is not available`** : l'image n'est pas la bonne.
> `docker-compose.yml` doit indiquer `image: pgvector/pgvector:pg16`, pas
> `postgres:16`. Après correction, repars propre :
> `docker compose down -v` puis reprends à l'étape 5.

---

## Étape 7 — Lancer l'API

```bash
uvicorn app.main:app --reload
```

```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Ouvre **http://localhost:8000/docs**. Tu dois voir Swagger avec 39 endpoints.

Laisse ce terminal ouvert. Pour la suite, ouvre-en un second et réactive le
venv (étape 2).

---

## Étape 8 — Lancer les tests

Dans le second terminal :

```bash
pytest
```

**Attendu : `30 passed`.**

C'est ton vrai point de contrôle. Si tu as ça, le socle est bon.

Pour le détail :

```bash
pytest -v
```

Les tests tournent contre le vrai PostgreSQL, pas contre SQLite : les types
`INET`, `JSONB` et `vector` ne s'y comportent pas de la même manière.

---

## Étape 9 — Ingérer les référentiels

**Toujours commencer par le mode simulation**, qui n'écrit rien en base :

```bash
python -m app.ingestion.cli --dry-run
```

Pour chaque texte, tu dois voir l'empreinte SHA-256, le nombre d'articles
extraits et un aperçu des cinq premiers.

Ordres de grandeur attendus : **RGPD environ 99 articles**, **NIS2 environ 46**,
**CSRD environ 8**. Si un référentiel remonte 0 ou 3 articles, la structure HTML
d'EUR-Lex a changé — envoie-moi la sortie, il faut ajuster les expressions
régulières dans `app/ingestion/eurlex.py`.

Quand la simulation est correcte :

```bash
python -m app.ingestion.cli
```

Premier lancement : fastembed télécharge le modèle `multilingual-e5-small`
(environ 120 Mo), une seule fois.

Sortie attendue :

```
 + rgpd       created      99 exigences
 + nis2       created      46 exigences
 + csrd       created       8 exigences
```

Relance la même commande : tout doit passer en `unchanged`. C'est la preuve que
l'ingestion est idempotente.

> **Si le téléchargement du modèle échoue** (proxy, réseau bridé), bascule sur
> le repli dans `.env` : `EMBEDDING_BACKEND=hashing`. L'application fonctionne,
> mais la recherche sémantique perd toute pertinence. À réserver au dépannage.

---

## Étape 10 — Test manuel du parcours complet

Dans Swagger, `POST /api/v1/auth/register`, **Try it out**, ce corps :

```json
{
  "email": "sarah@exemple.fr",
  "password": "Compliance!2026x",
  "full_name": "Sarah Test",
  "organization_name": "Acme SAS",
  "accept_terms": true
}
```

**201** attendu. Note l'`organization_id` dans la réponse.

Le mot de passe doit faire 12 caractères minimum et combiner trois types parmi
minuscules, majuscules, chiffres, caractères spéciaux — sinon 422.

Puis `POST /api/v1/auth/login`, copie l'`access_token`, remonte en haut de la
page, clique **Authorize**, colle-le.

Ensuite, dans l'ordre :

| Endpoint | Attendu |
|---|---|
| `GET /api/v1/auth/me` | 200, profil et rôle owner |
| `GET /api/v1/frameworks` | 200, les trois référentiels |
| `GET /api/v1/frameworks/rgpd/requirements` | 200, les articles du RGPD |
| `POST /api/v1/orgs/{org_id}/audits` | 201 — `{"title": "Audit RGPD 2026", "framework": "rgpd"}` |
| `POST .../audits/{audit_id}/documents` | 201 — déposer un `.txt` ou `.pdf` |
| `POST .../audits/{audit_id}/run` | 200, statut `completed` et un score |
| `GET .../audits/{audit_id}/findings` | 200, les non-conformités |
| `POST .../audits/{audit_id}/reports` | 201, version 1 |
| `GET .../reports/1/download` | le rapport HTML |
| `GET /api/v1/orgs/{org_id}/activity` | 200, toutes tes actions journalisées |
| `GET /api/v1/privacy/export` | 200, export RGPD |

Le lien de vérification d'e-mail s'affiche dans le terminal d'uvicorn, préfixé
`[DEV]` : il n'y a pas d'envoi de mail en développement.

---

## Étape 11 — Mettre sous Git

```bash
cd ..                      # revenir à la racine du projet
git init
git add .
git status                 # VÉRIFIE que .env n'apparaît PAS
git commit -m "feat: socle multi-tenant, referentiels et moteur d'audit"
```

Si `.env` apparaît, arrête tout et corrige `.gitignore` avant de committer. Un
`JWT_SECRET` poussé sur GitHub est compromis définitivement — même supprimé
ensuite, il reste dans l'historique.

Puis, après création d'un dépôt vide sur GitHub :

```bash
git remote add origin https://github.com/TON_COMPTE/complianceai-studio.git
git branch -M main
git push -u origin main
```

---

## Commandes du quotidien

```bash
# Démarrer une session
cd backend
.\.venv\Scripts\Activate.ps1        # ou source .venv/bin/activate
docker compose up -d db
uvicorn app.main:app --reload

# Arrêter
Ctrl+C
docker compose stop db

# Après modification des modèles SQLAlchemy
alembic revision --autogenerate -m "description"
alembic upgrade head

# Repartir d'une base vide
docker compose down -v
docker compose up -d db
alembic upgrade head
python -m app.ingestion.cli
```

---

## Erreurs fréquentes

| Symptôme | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: No module named 'app'` | mauvais dossier | se placer dans `backend/` |
| `ModuleNotFoundError: No module named 'fastapi'` | venv non activé | réactiver (étape 2) |
| `connection refused` sur 5432 | conteneur arrêté | `docker compose up -d db` |
| `password authentication failed` | `.env` désynchronisé du compose | user et mot de passe `compliance` |
| `Target database is not up to date` | migration en attente | `alembic upgrade head` |
| `JWT_SECRET field required` | `.env` absent ou mal placé | il doit être dans `backend/` |
| `422` sur register | mot de passe trop faible | lire le champ `errors` de la réponse |
| `429 Too Many Requests` | limitation de débit | attendre, ou `RATE_LIMIT_ENABLED=false` en local |
| `401` sur une route protégée | token expiré (15 min) | se reconnecter |
| `Le référentiel 'rgpd' n'a pas encore été ingéré` | étape 9 non faite | `python -m app.ingestion.cli` |
| `Aucun article extrait` | structure EUR-Lex modifiée | relancer en `--dry-run` et me transmettre la sortie |
| `vector dimension mismatch` | `EMBEDDING_DIM` modifié après migration | remettre 384, ou `docker compose down -v` et tout rejouer |

---

## Prochaine étape

Une fois `30 passed` et l'ingestion réussie, il reste le frontend React :
contexte d'authentification, rafraîchissement silencieux du jeton, sélecteur
d'organisation, écrans d'audit et visualisation du score.
