# Document de référence des normes de programmation — ComplianceAI Studio

**Livrable RNCP** — compétence CC1.1 (activité optionnelle 1)
**Version** 2.1 · **Portée** backend Python et frontend JavaScript natif (sans framework ni étape de build — voir DA-06, docs/architecture.md)

---

## 1. Objet et portée

Ce document fixe les règles de production de code du projet. Il est
volontairement univoque : chaque règle est soit automatiquement vérifiable,
soit formulée de manière à ne pas prêter à interprétation. Toute règle non
outillée est signalée comme telle.

Trois niveaux d'exigence :

- **Bloquant** — la règle est vérifiée en intégration continue ; sa violation
  empêche la fusion.
- **Requis** — la règle est vérifiée en revue de code.
- **Recommandé** — bonne pratique, non bloquante.

## 2. Outillage

| Rôle | Outil | Niveau |
|---|---|---|
| Analyse statique Python | `ruff check` (règles E9, F — erreurs et pyflakes) | Bloquant (CI : job `qualite-code`) |
| Tests | `pytest` | Bloquant (CI : job `backend-tests`) |
| Vulnérabilités des dépendances | `pip-audit` | Rapport, non bloquant (CI : job `qualite-code` — voir §9) |
| Formatage Python | `ruff format` (ligne 100) | Non outillé en CI — 48 fichiers sur 80 ne le respectent pas encore à ce jour ; adopter l'outil suppose une passe de reformatage dédiée, pas mêlée à un changement de comportement (règle §8) |
| Typage Python | `mypy --strict` sur `app/` | Non outillé — jamais exécuté sur ce dépôt, portée non évaluée |
| Secrets en clair | `gitleaks` | Non outillé |

Le formatage n'est pas encore un contrôle automatisé sur ce dépôt : en
attendant, il reste sujet de revue de code, pas seulement de l'outil.

## 3. Nommage

| Élément | Convention | Exemple |
|---|---|---|
| Module Python | `snake_case`, singulier | `activity.py` |
| Classe | `PascalCase` | `OrgContext` |
| Fonction, variable | `snake_case` | `verify_password` |
| Constante | `UPPER_SNAKE_CASE` | `MAX_FAILED_LOGINS` |
| Fonction privée de module | préfixe `_` | `_issue_refresh` |
| Table SQL | `snake_case` pluriel | `activity_logs` |
| Clé étrangère | `<singulier>_id` | `organization_id` |
| Index | `ix_<table>_<colonnes>` | `ix_audits_org_created` |
| Contrainte d'unicité | `uq_<sens>` | `uq_report_version` |
| Fonction, variable JS | `camelCase`, verbe en français pour une fonction | `chargerReferentielDetail` |
| Constante JS (module) | `UPPER_SNAKE_CASE` | `VIDEO_DEMO_URL` |

Les identifiants sont en anglais dans le code, les messages destinés à
l'utilisateur en français. Les commentaires expliquant une décision sont en
français, langue de l'équipe et du jury.

## 4. Règles de lisibilité et d'expressivité

**R-01 (Requis).** Une fonction ne dépasse pas 50 lignes ni 4 niveaux
d'indentation. Au-delà, elle est décomposée.

**R-02 (Bloquant).** Toute fonction publique est annotée en types, paramètres et
retour compris. `Any` est interdit sauf justification en commentaire.

**R-03 (Requis).** Le commentaire explique *pourquoi*, jamais *quoi*. Le code
doit se passer de commentaire sur son intention ; il en reçoit un lorsque la
décision derrière lui n'est pas évidente.

```python
# Mauvais — paraphrase le code
user.failed_login_count += 1  # incrémente le compteur

# Bon — explique une décision non évidente
# Hachage à vide : maintient un temps de réponse constant et empêche
# l'énumération des comptes par mesure de latence.
hash_password(payload.password)
```

**R-04 (Requis).** Pas de nombre magique. Toute valeur porteuse de sens métier
est une constante nommée au niveau du module.

**R-05 (Requis).** Sortie anticipée plutôt qu'imbrication : les cas d'erreur
sont traités et écartés en tête de fonction.

**R-06 (Bloquant).** Aucun `print` en dehors des blocs explicitement gardés par
`settings.DEBUG`. La journalisation passe par le module `logging`.

## 5. Règles de sécurité

**S-01 (Bloquant).** Aucune requête SQL construite par concaténation ou
interpolation de chaîne. Exclusivement l'ORM ou `text()` avec paramètres liés.

**S-02 (Bloquant).** Aucun secret dans le dépôt. Toute valeur sensible transite
par une variable d'environnement, absente du dépôt et présente dans
`.env.example` avec une valeur factice.

**S-03 (Bloquant).** Toute entrée externe est validée par un schéma Pydantic
avec bornes explicites (`min_length`, `max_length`, `ge`, `le`). Aucun `dict`
brut ne franchit la couche API.

**S-04 (Bloquant).** Les mots de passe sont hachés avec Argon2id via
`app.core.security`. Aucun autre algorithme n'est autorisé, y compris pour un
prototype.

**S-05 (Bloquant).** Toute route non publique déclare une dépendance
d'authentification. Toute route sous `/orgs/{org_id}` déclare `get_org_context`
ou `require_role`. Une route métier sans dépendance de contexte est un défaut
bloquant.

**S-06 (Requis).** Un message d'erreur ne révèle jamais l'existence d'une
ressource à un utilisateur non habilité : on répond 404, pas 403.

**S-07 (Requis).** Aucune donnée personnelle ni secret dans les journaux. Les
champs sensibles sont remplacés par `[REDACTED]` via `services.activity`.

**S-08 (Bloquant).** Les dépendances sont épinglées à une version exacte dans
`requirements.txt`. `pip-audit` s'exécute en intégration continue.

## 6. Base de données

**B-01 (Bloquant).** Toute évolution de schéma passe par une migration Alembic
révisable. Aucune modification manuelle en base.

**B-02 (Requis).** Toute migration implémente `downgrade()`.

**B-03 (Requis).** Toute clé étrangère déclare un `ondelete` explicite. Le choix
entre `CASCADE` et `SET NULL` est une décision métier : les données de l'audit
suivent l'organisation, les traces d'activité lui survivent.

**B-04 (Requis).** Toute colonne servant à filtrer ou trier une liste est
indexée. Les index composites suivent l'ordre réel des prédicats.

**B-05 (Bloquant).** Aucune écriture destructive sur `activity_logs`.

## 7. Tests

**T-01 (Bloquant).** Toute correction de bogue est précédée d'un test qui
reproduit le défaut.

**T-02 (Bloquant).** Toute règle de sécurité de la section 5 est couverte par un
test d'intégration : cloisonnement entre organisations, RBAC, verrouillage de
compte, rotation et rejeu de jeton.

**T-03 (Requis).** Un test suit la structure préparation / action / vérification
et son nom décrit le comportement attendu, pas la fonction appelée
(`test_user_cannot_reach_another_organization`, non `test_get_org`).

**T-04 (Requis).** Les tests s'exécutent contre PostgreSQL, jamais SQLite : les
types `INET`, `JSONB`, `vector` et les contraintes différées ne s'y comportent
pas de la même manière.

## 8. Contrôle de version

- Branches : `main` protégée, `feat/*`, `fix/*`, `docs/*`, `chore/*`.
- Messages au format Conventional Commits : `feat(auth): rotation des refresh tokens`.
- Une fusion exige : intégration continue au vert, au moins une revue,
  historique linéaire (`squash`).
- Un commit ne mélange jamais une reformulation et un changement de
  comportement.

## 9. Métriques de validation

| Métrique | Cible | Mesure au 2026-09-20 |
|---|---|---|
| Couverture de tests globale | ≥ 70 % | 79 % (mesuré ponctuellement, `pytest --cov` — pas encore un seuil bloquant en CI) |
| Couverture de `core/security.py` | 100 % | 91 % — 4 lignes non couvertes |
| Complexité cyclomatique | ≤ 10 par fonction | Non bloquant en CI ; un dépassement connu (`audit_engine.py::run_audit`, complexité 18 — le point de convergence attendu de l'orchestration, pas un signe de dérive répandue) |
| Erreurs de typage | — | `mypy` jamais exécuté sur ce dépôt, pas de cible fixée |
| Vulnérabilités des dépendances | — | `pip-audit` en rapport (non bloquant) : 150 CVE relevées sur 6 paquets le 2026-09-20, 2 corrigées dans la foulée (`pyjwt`, `python-multipart`), 3 en attente de montée majeure planifiée (`pypdf`, `pillow`, `starlette`) |
| Secrets détectés | — | `gitleaks` non outillé, aucun scan effectué |
| Durée de la CI | — | Non mesurée comme cible ; les jobs tournent en parallèle sur GitHub Actions (`qualite-code`, `backend-tests`, `frontend-e2e` indépendants) |

Ce tableau est un état des lieux daté, pas une liste de garanties : les
cellules « — » signalent une métrique non instrumentée plutôt qu'un seuil
atteint par défaut.

## 10. Cohérence des règles

Les règles ci-dessus ont été vérifiées comme mutuellement compatibles. Deux
tensions apparentes sont arbitrées explicitement :

- R-03 (peu de commentaires) et S-04 / DA-02 (justifier les choix de sécurité) :
  les décisions de sécurité sont commentées ; les mécanismes ne le sont pas.
- T-04 (tests sur PostgreSQL) et la rapidité de la CI : un conteneur PostgreSQL
  en service GitHub Actions démarre en moins de 10 secondes, l'impact reste
  dans le budget de 5 minutes.
