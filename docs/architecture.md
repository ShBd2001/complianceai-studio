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

Justification : l'équipe compte cinq personnes, le trafic attendu est de quelques
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
│  Présentation   SPA JavaScript vanilla (un seul │
│                 fichier statique, sans build)   │
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
`organization_id`. L'isolation est applicative : la dépendance
`get_org_context` vérifie l'appartenance avant toute exécution, et
`organization_id` figure explicitement dans la clause `WHERE` de chaque
requête — y compris pour la recherche vectorielle/lexicale sur les documents
client (`app/services/rag.py`), qui filtre par organisation et par campagne
avant tout classement. Ce cloisonnement est couvert par des tests
d'intégration (`backend/tests/test_scoping.py`, `test_rag_retrievers.py`)
qui vérifient qu'un fragment d'une autre organisation, ou d'une autre
campagne de la même organisation, n'est jamais retourné.

*Alternative écartée.* Un schéma PostgreSQL par organisation isole mieux mais
rend les migrations coûteuses (N schémas à faire évoluer) et sature le
catalogue au-delà de quelques centaines de locataires.

*Renforcement prévu, non activé.* Row Level Security sur les tables métier,
en défense en profondeur (même une requête applicative fautive ne pourrait
pas franchir la frontière du locataire). Non activée avant la soutenance :
la table `findings` n'a pas de colonne `organization_id` propre (elle
dérive d'`audits`), et le planificateur (`app/services/scheduler.py`)
traite plusieurs organisations dans une même session applicative — activer
RLS sans avoir traité ces deux points romprait silencieusement des chemins
qui fonctionnent aujourd'hui. Chantier identifié, pas engagé.

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

### DA-06 — Frontend en JavaScript natif, sans framework ni étape de build

*Décision.* Une page unique (`frontend/index.html`), sans dépendance ni
bundler : le routage, l'état et le rendu sont gérés par du JavaScript natif.

*Justification.* Le même raisonnement d'échelle qu'au §3 (style
d'architecture) s'applique côté client : un framework (React, Vue) et sa chaîne de
build (Vite, npm) ajoutent une surface de maintenance — versions à faire
évoluer, temps de build, dépendances transitives à auditer — sans bénéfice
proportionné pour une application qui ne justifie pas de composants
réutilisables à grande échelle ni de rendu complexe. Le fichier statique se
déploie directement sur l'hébergement Render du frontend, sans pipeline de
build séparé à maintenir.

*Conséquences.* Positives : zéro dépendance à auditer côté client (voir DA-01
sur la réduction de la surface d'attaque), démarrage instantané en
développement (`python -m http.server`), aucun risque de dérive entre version
de build et version servie. Négatives : pas de vérification de types
statique côté client, découpage en composants moins strict qu'un framework ne
l'imposerait — compensé par une convention de nommage stricte des fonctions
et une revue de code systématique sur `frontend/index.html`.

*Réversibilité.* Le frontend consomme l'API par HTTP/JSON standard, sans
couplage à son implémentation : une réécriture en React resterait possible
sans toucher au backend.

### DA-07 — Méthode de recherche configurable, lexicale par défaut

*Décision.* La recherche des passages pertinents (`app/services/rag.py`)
propose trois méthodes, choisies par `RAG_RETRIEVER` (`"lexical"` |
`"semantique"` | `"hybride"`, validé au démarrage) : un classement lexical
(recouvrement pondéré par occurrence/longueur, calculé en Python — copie
fidèle de l'algorithme mesuré dans le harnais de validation, pas une
réimplémentation), un classement sémantique (pgvector, distance cosinus,
code inchangé), et un mode hybride qui fusionne les deux par fusion de rangs
(Reciprocal Rank Fusion, k = 60). Le défaut de production est `"lexical"`.

*Justification.* Mesuré sur le corpus de validation
(`validation/comparer_retrievers.py`, résultats dans
`validation/comparaison_retrievers.json`, ~210 articles évalués) : sur des
textes réglementaires, le lexical seul bat le sémantique seul sur toutes les
métriques (exactitude 91,9 % contre 85,2 %, rappel parfait contre 4 faux
négatifs) — la terminologie exacte compte plus que la paraphrase quand il
s'agit de citer un article de loi. C'est cet algorithme précis, copié depuis
`evaluation/evaluateur.py::retriever_lexical` (le backend n'importe jamais le
paquet `evaluation`, deux paquets séparés), qui est mesuré : une recherche
plein texte PostgreSQL aurait un comportement différent, non mesuré
indépendamment, et aurait rompu la fidélité à la mesure qui justifie le
choix. Le mode hybride reste disponible et configurable : un document client
réel ne reprend pas toujours le vocabulaire exact du texte de loi, et l'écart
mesuré avec l'hybride (90,5 %, soit 1,4 point) n'est pas significatif sur ce
corpus.

*Conséquences.* Positives : aucune dépendance ni migration de schéma
nécessaire (le classement lexical travaille sur les colonnes déjà
existantes) ; la méthode reste changeable par configuration seule, sans
déploiement de code. Négatives : le classement lexical charge en mémoire
l'ensemble des fragments du périmètre interrogé (organisation/campagne) pour
les trier en Python, contre une requête indexée limitée en mode sémantique —
acceptable au volume actuel (quelques documents par audit), à revoir si le
volume par campagne grossit significativement ; `Passage.distance` (dont
dépend le repli heuristique sans modèle de langage) est une distance cosinus
réelle en mode sémantique/hybride, mais une approximation monotone non
calibrée indépendamment du score lexical en mode lexical pur.

*Réversibilité.* Changement de configuration seul (`RAG_RETRIEVER`), sans
migration : revenir au sémantique (le comportement d'avant cette décision)
ne demande qu'un redéploiement avec la variable modifiée.

### DA-08 — Filtre d'éligibilité multi-référentiel, jamais au bénéfice du doute

*Décision.* `app/services/eligibilite.py` tranche en amont l'applicabilité
de certaines obligations à partir du profil déclaratif de l'organisation
(`organizations`, colonnes nullables), sans appel au modèle : RGPD
(art. 13, 14, 30, 37) depuis la Tâche 8, étendu par la Tâche F1 à NIS2,
DORA et AI Act (~40 règles supplémentaires, 5 nouveaux champs de profil).
Trois verdicts — `APPLICABLE`, `EXEMPTE`, `A_VERIFIER` — indexés sur
`(référentiel, numéro d'article)` : l'article 30 du RGPD (registre des
traitements) et celui de NIS2 (notification volontaire) n'ont aucun
rapport, malgré le même numéro. Une information non renseignée ne produit
**jamais** une exemption : `A_VERIFIER` fait suivre à l'obligation le
parcours normal d'évaluation par le modèle, exactement comme si le filtre
n'existait pas.

*Justification.* Le coût d'un faux négatif (obligation réellement due,
écartée à tort) est sans commune mesure avec celui d'un faux positif
(obligation non due, évaluée pour rien par le modèle) — un outil d'audit
qui exempte à tort perd toute valeur probante. Certains référentiels ont
des règles plus étroites que leur statut général ne le laisse supposer :
un article NIS2 peut cibler spécifiquement les fournisseurs de DNS/registre
(art. 27/28) au sein des seules entités essentielles/importantes, un
article DORA peut être réservé aux autorités européennes de surveillance
et donc toujours hors périmètre pour une organisation cliente (art. 15,
20, 21), un article AI Act peut ne jamais être exemptable (art. 5,
pratiques interdites) quel que soit le profil. Ces distinctions sont
posées article par article en lisant le texte ingéré, pas déduites d'un
principe général par référentiel.

*Conséquences.* Positives : les obligations manifestement hors champ
n'occupent plus de temps de calcul ni de quota modèle, avec une
justification tracée sur le constat. Un avertissement non bloquant
(`scope_warning`) est renvoyé à la création d'une campagne si le profil
indique que le référentiel entier ne s'applique pas. Négatives : le filtre
ne vaut que ce que vaut le profil déclaré — un profil erroné ou non
renseigné ne fait courir aucun risque d'exemption abusive (prudence
systématique), mais ne fait pas non plus gagner le temps de calcul qu'un
profil correctement renseigné permettrait. Portée : ce filtre concerne le
backend FastAPI, pas le harnais du laboratoire (`evaluation/`), pipeline
distinct.

*Réversibilité.* Purement additive : retirer une règle de `REGLES` fait
retomber l'article concerné sur le parcours normal d'évaluation par le
modèle, sans migration ni effet de bord.

### DA-09 — Second avis ciblé sur les verdicts de conformité peu sûrs

*Décision.* `LLM_TEMPERATURE=0.0` (le réglage le plus déterministe possible
côté requête) n'élimine pas la variance d'un appel à l'autre : sur
l'infrastructure d'inférence de Groq, le modèle (`openai/gpt-oss-120b`, à
experts/MoE) n'est pas garanti bit-à-bit reproductible même à température
nulle, le routage entre experts pouvant être sensible au lot d'autres
requêtes traitées en parallèle sur le même matériel à cet instant — un
phénomène mesuré indépendamment côté laboratoire de validation
(`validation/harnais.py`, `verdicts_instables`, non nul même cache vidé).
Dans `evaluate_requirement()` (`app/services/audit_engine.py`), une
conformité ("oui"/"partiel") dont la citation est vérifiée mais dont la
confiance déclarée par le modèle reste sous `REVIEW_CONFIDENCE_THRESHOLD`
déclenche un second appel indépendant, même prompt : la conformité n'est
publiée que si les deux avis s'accordent, sinon le verdict est ramené à
"indéterminé" par prudence.

*Justification.* Un vote majoritaire sur *toutes* les exigences (déjà
outillé côté laboratoire, `validation/run_validation.py --vote`) est la
mitigation la plus robuste, mais triple le coût et la durée de chaque
analyse en production, en permanence — un choix économique, pas seulement
technique, qui reste à trancher par l'équipe. Cibler uniquement les cas
déjà signalés incertains (confiance sous le seuil de revue humaine) capture
la même instabilité là où elle est la plus probable, pour une fraction du
coût : ces exigences sont de toute façon déjà promises à une vérification
humaine, le second appel ne fait qu'éviter d'afficher à tort une conformité
qu'un second passage ne confirme pas.

*Conséquences.* Positives : réduit les bascules "oui" ↔ "indéterminé" d'une
exécution à l'autre sur le sous-ensemble le plus exposé, sans changer le
coût des exigences déjà confiantes. Négatives : ne couvre pas l'instabilité
sur les verdicts "non"/"non applicable" (jugée moins grave — le risque d'un
faux "non" est bien moindre que celui d'un faux "oui", voir la suite de
tests) ni sur un "oui" confiant qui se révèle instable malgré tout (cas non
mesuré comme fréquent) ; un second appel qui échoue (panne, quota) conserve
le premier verdict tel quel plutôt que de le perdre.

*Réversibilité.* Isolé dans `evaluate_requirement()` : retirer le bloc du
second avis fait retomber sur le comportement précédent (un seul appel),
sans migration ni effet sur le reste du moteur.

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

| Sujet | Situation | Traitement |
|---|---|---|
| Stockage des documents | Système de fichiers local, sur un disque persistant Render (1 Go, monté sur `/var/data`, `STORAGE_DIR=/var/data/storage`) depuis le 2026-09-24 ; survit à un redéploiement/redémarrage, pas encore de stockage objet externe | Migration vers un stockage compatible S3 si le volume dépasse la capacité du disque |
| Analyse synchrone | Le calcul tourne dans un thread dédié (FastAPI ne bloque pas les autres requêtes), mais l'appelant attend la fin complète de l'analyse | File de tâches en arrière-plan pour les audits longs |
| Dépendances avec vulnérabilités connues | `pypdf` et `starlette` corrigés (montée de version validée par la suite de non-régression) ; `pillow` (dépendance transitive de `fastembed`, moteur d'embeddings) volontairement laissé en l'état : la version disponible change la stratégie de pooling (CLS → moyenne), un risque de corruption silencieuse de la recherche sémantique plus grave que la CVE elle-même | Montée de `fastembed`/`pillow` après audit de l'impact sur la qualité du RAG, pas seulement sur la compatibilité |
| Authentification unique (SSO/SAML) | Non implémentée, non annoncée (retirée de la page Tarifs) | Chantier non engagé, pas de calendrier |
| Limite de débit en mémoire | `slowapi` n'a pas de backend partagé (Redis) : passer à plusieurs processus applicatifs multiplierait silencieusement les seuils de protection | Ajout de Redis si une mise à l'échelle horizontale devient nécessaire |
| Quotas par offre | Campagnes/mois et utilisateurs appliqués côté serveur ; nombre d'organisations par palier et restriction "1 référentiel" de l'offre Essentiel non appliqués (ambiguïté produit sur le cas d'un utilisateur déjà multi-organisations) | Décision produit à trancher avant application |
| Mesure de précision hors RGPD | Seul le RGPD dispose d'un corpus de validation mesuré (`corpus/`, 15 documents, 210 verdicts) ; `corpus_nis2/`, `corpus_dora/`, `corpus_ai_act/` sont des squelettes vides (Tâche F2) — le filtre d'éligibilité (DA-08) et le moteur d'audit tournent sur ces référentiels sans qu'aucune métrique de précision n'ait encore été mesurée dessus | Composition du corpus et de sa vérité terrain par l'équipe, puis `python -m validation.evaluate --referentiel {nis2,dora,ai_act}` |

Ces limites sont documentées volontairement plutôt que masquées : certaines
sont des choix assumés pour l'échelle actuelle du projet, d'autres des
chantiers identifiés mais non engagés faute de priorité.

## 7. Pour aller plus loin

- OWASP Application Security Verification Standard v4.0
- OWASP Cheat Sheet — Authentication, Session Management, Password Storage
- ANSSI, *Recommandations relatives à l'authentification multifacteur*
- Documentation pgvector — indexation HNSW
- CNIL, *Guide de la sécurité des données personnelles*
