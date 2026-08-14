# Document de référence de l'architecture — ComplianceAI Studio

**Livrable RNCP** — compétence CC1.1 (activité optionnelle 1)
**Version** 2.0 · **Statut** validé pour la phase de production

---

## 1. Objet du document

Ce document fixe le modèle d'architecture de la solution, justifie les choix
technologiques et sert de référence commune à l'équipe de développement. Il est
destiné à être lu par un développeur rejoignant le projet comme par un
évaluateur technique externe.

## 2. Analyse fonctionnelle

La solution répond à un besoin identifié : les PME et ETI françaises soumises au
RGPD et, depuis 2024, à la directive NIS2, ne disposent ni de budget pour un
audit de conformité classique (12 000 à 40 000 €) ni de compétence interne pour
le mener. ComplianceAI Studio automatise la phase d'analyse documentaire d'un
audit et produit un rapport de non-conformités hiérarchisées.

Fonctions principales :

| Code | Fonction | Acteur |
|---|---|---|
| F1 | Créer un compte et une organisation | Visiteur |
| F2 | Inviter des collaborateurs avec un rôle | Owner / Admin |
| F3 | Lancer une campagne d'audit sur un référentiel | Auditeur |
| F4 | Déposer des documents à analyser | Auditeur |
| F5 | Consulter les non-conformités détectées | Tout membre |
| F6 | Générer et versionner un rapport | Auditeur |
| F7 | Suivre l'évolution du score de conformité | Tout membre |
| F8 | Consulter le journal d'activité | Admin |
| F9 | Exporter ou supprimer ses données personnelles | Tout membre |

## 3. Style d'architecture retenu

**Monolithe modulaire en couches**, et non microservices.

Justification : l'équipe compte une personne, le trafic attendu est de quelques
dizaines d'organisations, et la cohérence transactionnelle entre un audit, ses
documents et ses résultats est forte. Une découpe en microservices imposerait
une complexité opérationnelle (orchestration, transactions distribuées,
observabilité répartie) sans bénéfice mesurable à cette échelle. Le découpage
en modules applicatifs permet, si le besoin apparaît, d'extraire ultérieurement
le moteur d'analyse en service autonome — c'est d'ailleurs le premier candidat
à l'extraction, car son profil de charge (rafales CPU longues) diffère de celui
de l'API (requêtes courtes).

### Couches

```
┌─────────────────────────────────────────────────┐
│  Présentation   React 18 + TypeScript + Vite    │
└───────────────────────┬─────────────────────────┘
                        │ HTTPS / JSON
┌───────────────────────▼─────────────────────────┐
│  API            FastAPI — routage, validation,  │
│                 authentification, RBAC          │
├─────────────────────────────────────────────────┤
│  Services       logique métier : audit, RAG,    │
│                 génération de rapport, journal  │
├─────────────────────────────────────────────────┤
│  Persistance    SQLAlchemy 2.0 ORM + Alembic    │
└───────────────────────┬─────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────┐
│  PostgreSQL 16 + pgvector                       │
│  relationnel · vectoriel · journal              │
└─────────────────────────────────────────────────┘
                        │
                  Groq API (LLM)
```

Règle de dépendance : une couche ne connaît que la couche immédiatement
inférieure. Un routeur n'accède jamais directement à l'ORM pour de la logique
métier ; il délègue à un service.

## 4. Décisions d'architecture

### DA-01 — PostgreSQL comme système de persistance unique

*Contexte.* La version 1 utilisait ChromaDB pour les vecteurs et SQLite pour le
reste.

*Décision.* Unifier dans PostgreSQL 16 avec l'extension pgvector.

*Conséquences.* Positives : cohérence transactionnelle entre les métadonnées
d'un document et ses embeddings ; filtrage du corpus vectoriel par
`organization_id` directement dans la clause `WHERE`, ce qui rend une fuite
inter-locataires structurellement impossible ; un seul service à sauvegarder et
superviser ; persistance garantie sur un hébergement à système de fichiers
éphémère, là où un index ChromaDB sur disque local serait perdu à chaque
redéploiement. Négatives : pgvector est moins performant qu'un moteur vectoriel
dédié au-delà de quelques millions de vecteurs — seuil hors de portée du projet.

*Réversibilité.* L'accès vectoriel passe par une interface `VectorStore`. Un
adaptateur ChromaDB ou Qdrant peut être substitué sans toucher au code métier.

### DA-02 — Authentification par JWT court + refresh opaque

*Décision.* Access token JWT de 15 minutes transmis dans l'en-tête
`Authorization`, refresh token aléatoire de 256 bits en cookie `HttpOnly`.

*Justification.* Le JWT est sans état, donc non révocable : sa durée de vie est
volontairement courte. Le refresh token, lui, est stocké haché en base et donc
révocable individuellement — un vidage de la table ne permet pas de rejouer une
session. Placer le refresh dans un cookie `HttpOnly` le soustrait à tout accès
JavaScript, ce qui neutralise le vol par XSS ; `SameSite=Strict` couvre le CSRF.

*Rotation et détection de rejeu.* Chaque appel à `/refresh` révoque le jeton
présenté et en émet un nouveau, rattaché à la même `family_id`. Si un jeton déjà
révoqué est présenté, c'est qu'il a été volé : toute la famille est invalidée et
l'utilisateur doit se reconnecter.

### DA-03 — Multi-locataire par colonne discriminante

*Décision.* Une base unique ; chaque enregistrement métier porte un
`organization_id`. L'accès passe obligatoirement par la dépendance
`get_org_context`, qui vérifie l'appartenance avant toute exécution.

*Alternative écartée.* Un schéma PostgreSQL par organisation isole mieux mais
rend les migrations coûteuses (N schémas à faire évoluer) et sature le
catalogue au-delà de quelques centaines de locataires.

*Renforcement prévu.* Activation de Row Level Security sur les tables métier,
en défense en profondeur : même une requête applicative fautive ne pourrait pas
franchir la frontière du locataire.

### DA-04 — Journal d'activité en ajout seul

*Décision.* La table `activity_logs` n'est exposée qu'en lecture. Aucune route
n'émet d'`UPDATE` ni de `DELETE` dessus.

*Justification.* Elle sert simultanément de registre des activités de traitement
(RGPD art. 30) et de source de détection d'incident (NIS2 art. 21.2.b). Un
journal modifiable n'a aucune valeur probante.

### DA-05 — Traçabilité des décisions du modèle

*Décision.* Chaque non-conformité enregistre le modèle utilisé, un score de
confiance et le document source.

*Justification.* Une recommandation de conformité opposable à un client doit
être justifiable. C'est aussi une exigence anticipée du règlement européen sur
l'IA pour les systèmes d'aide à la décision.

## 5. Vue de déploiement

```
Navigateur ──► CDN (front statique)
                    │
                    ▼
            Render — service web Docker
            uvicorn · utilisateur non privilégié · /health
                    │
                    ▼
            PostgreSQL managé (TLS, sauvegardes)
                    │
                    ▼
              Groq API (sortie HTTPS)
```

Les migrations Alembic sont jouées au démarrage du conteneur, avant le
lancement du serveur : un déploiement ne peut pas exposer une application dont
le schéma est en retard.

## 6. Points de vigilance connus

| Sujet | Situation | Traitement prévu |
|---|---|---|
| Mise en veille de l'hébergement gratuit | 50 s de réveil après 15 min d'inactivité | Cron de maintien en éveil ; plan payant en production |
| Envoi d'e-mails | Non branché, jetons affichés en console en développement | Intégration d'un service transactionnel |
| Stockage des documents | Système de fichiers local | Migration vers un stockage objet compatible S3 |
| Analyse synchrone | Un audit long bloque une requête HTTP | File de tâches en arrière-plan |

Ces limites sont assumées à ce stade et documentées volontairement : elles
constituent la feuille de route technique de la version suivante.

## 7. Pour aller plus loin

- OWASP Application Security Verification Standard v4.0
- OWASP Cheat Sheet — Authentication, Session Management, Password Storage
- ANSSI, *Recommandations relatives à l'authentification multifacteur*
- Documentation pgvector — indexation HNSW
- CNIL, *Guide de la sécurité des données personnelles*
