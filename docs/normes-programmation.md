# Document de référence des normes de programmation — ComplianceAI Studio

**Livrable RNCP** — compétence CC1.1 (activité optionnelle 1)
**Version** 2.0 · **Portée** backend Python et frontend TypeScript

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
| Formatage Python | `ruff format` (ligne 100) | Bloquant |
| Analyse statique Python | `ruff check` | Bloquant |
| Typage Python | `mypy --strict` sur `app/` | Bloquant |
| Tests | `pytest`, couverture ≥ 70 % | Bloquant |
| Vulnérabilités des dépendances | `pip-audit` | Bloquant |
| Secrets en clair | `gitleaks` | Bloquant |
| Formatage TypeScript | `prettier` | Bloquant |
| Analyse statique TypeScript | `eslint`, `tsc --noEmit` | Bloquant |

Le formatage n'est pas discuté en revue : il est imposé par l'outil. La revue
porte sur la conception, la sécurité et la lisibilité.

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
| Composant React | `PascalCase.tsx` | `LoginForm.tsx` |
| Hook React | préfixe `use` | `useAuth.ts` |

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

| Métrique | Seuil | Mesure |
|---|---|---|
| Couverture de tests | ≥ 70 % global, 100 % sur `core/security.py` | `pytest --cov` |
| Complexité cyclomatique | ≤ 10 par fonction | `ruff` (règle C901) |
| Erreurs de typage | 0 | `mypy --strict` |
| Vulnérabilités haute ou critique | 0 | `pip-audit` |
| Secrets détectés | 0 | `gitleaks` |
| Durée de la CI | ≤ 5 min | GitHub Actions |

## 10. Cohérence des règles

Les règles ci-dessus ont été vérifiées comme mutuellement compatibles. Deux
tensions apparentes sont arbitrées explicitement :

- R-03 (peu de commentaires) et S-04 / DA-02 (justifier les choix de sécurité) :
  les décisions de sécurité sont commentées ; les mécanismes ne le sont pas.
- T-04 (tests sur PostgreSQL) et la rapidité de la CI : un conteneur PostgreSQL
  en service GitHub Actions démarre en moins de 10 secondes, l'impact reste
  dans le budget de 5 minutes.
