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
Dans `evaluate_requirement()` (`app/services/audit_engine.py`), tout
premier verdict — quelle que soit sa valeur, y compris "indéterminé" et
"non_applicable" natifs (voir plus bas) — dont la confiance déclarée par le
modèle reste sous `SECOND_OPINION_CONFIDENCE_THRESHOLD` déclenche un ou
deux appels indépendants supplémentaires, même prompt (vote à 3). Le
verdict d'origine est conservé s'il obtient la majorité absolue des avis
recueillis ; si c'est une autre valeur qui l'obtient, la réponse complète
d'un avis qui la porte est adoptée à sa place (jamais seulement le mot-clé
"conforme" en gardant l'ancienne preuve et l'ancien constat) et repasse par
la même vérification de citation qu'un premier appel avant publication ; en
l'absence de toute majorité absolue, le verdict est ramené à "indéterminé"
par prudence.

*Mesure ayant motivé l'élargissement à "non".* La version initiale de ce
garde-fou ne couvrait que "oui"/"partiel". Deux exécutions indépendantes du
même document réel (même code, aucune modification entre les deux) ont
montré que **32 % des articles évalués changeaient de verdict** d'une
exécution à l'autre — et que la quasi-totalité de ces bascules se faisaient
depuis ou vers un "indéterminé" natif ("non" ↔ "indéterminé", "partiel" ↔
"indéterminé"), pas seulement depuis un "oui" non confirmé. Se limiter à
"oui"/"partiel" manquait donc l'essentiel de l'instabilité réellement
observée ; élargi à "non" en conséquence (commit `89834b2`).

*Mesure ayant motivé le passage à un vote à 3 et au relèvement du seuil.*
Après déploiement de `89834b2` sur Render, une même analyse relancée deux
fois sur le même document a continué de produire des écarts de score
importants (57,9 puis 65,5 sur 100, soit 7,6 points — écart mesuré en
production, code déployé confirmé identique entre les deux passages via
sondage 401/404 des routes plutôt que `/openapi.json`, désactivé en
production). Deux limites du mécanisme à deux appels expliquent cette
insuffisance : (1) le seuil de déclenchement (`REVIEW_CONFIDENCE_THRESHOLD`,
0,5, réutilisé par simplicité) manquait des cas observés instables jusqu'à
une confiance affichée de 0,6 ; (2) un unique second appel en désaccord
rétrograde systématiquement vers "indéterminé", alors que ce second appel
peut lui-même être le bruit plutôt que le premier — un simple 1-1 ne
justifie pas de trancher contre l'avis initial. Corrections apportées :
`SECOND_OPINION_CONFIDENCE_THRESHOLD` dédié, relevé à 0,7 ; et, en cas de
désaccord au second appel, un troisième avis indépendant tranche (motif
retenu s'il obtient la majorité absolue sur l'ensemble des avis recueillis,
premier appel inclus — jamais la valeur elle-même du troisième avis, pour
ne jamais publier un verdict dont le contenu, preuve et constat, ne
correspond plus à la conclusion affichée). Inspiré du vote majoritaire déjà
outillé côté laboratoire (`evaluation/evaluateur.py::evaluer_article_vote`,
`n_votes=3`, `collections.Counter`), réimplémenté localement dans
`audit_engine.py` sans jamais importer le package `evaluation` (DA-07). Le
laboratoire retient par défaut l'option la plus protectrice
("manquement") sur une pluralité fragile ; le moteur de production s'en
écarte délibérément, cohérent avec le reste du fichier : en l'absence de
majorité claire, la conformité **et** le manquement sont tous deux ramenés
à "indéterminé", jamais l'un ou l'autre affirmé sans confirmation.

*Justification.* Un vote majoritaire sur *toutes* les exigences (déjà
outillé côté laboratoire, `validation/run_validation.py --vote`) est la
mitigation la plus robuste, mais triple le coût et la durée de chaque
analyse en production, en permanence — un choix économique, pas seulement
technique, qui reste à trancher par l'équipe. Cibler uniquement les cas
déjà signalés incertains (confiance sous le seuil dédié) capture la même
instabilité là où elle est la plus probable, pour une fraction du coût :
ces exigences sont de toute façon déjà promises à une vérification
humaine, les appels supplémentaires ne font qu'éviter d'afficher à tort un
verdict qu'un vote indépendant ne confirme pas.

*Mesure ayant motivé l'extension à "indéterminé" et "non_applicable"
natifs.* Après déploiement du vote à 3 limité à "oui"/"partiel"/"non"
(commit `3648e3f`), une nouvelle comparaison même document / deux
exécutions a montré que l'écart de score ne se résorbait que marginalement
(68,9 puis 74,9, soit 6,0 points contre 7,6 avant ce commit) et que **14
articles sur 39 (36 %) changeaient encore de verdict** — une proportion
supérieure à la mesure initiale. Le détail des bascules a révélé la cause :
**12 des 14 concernaient un "indéterminé" ou un "non_applicable" natif**
("non" ↔ "indéterminé", "partiel" ↔ "indéterminé", "non_applicable" ↔
"indéterminé"), c'est-à-dire précisément les deux catégories que le
mécanisme excluait par construction. L'hypothèse de conception initiale —
"un indéterminé natif est déjà l'état terminal stable, un vote n'y changerait
rien" — s'est révélée fausse : un "indéterminé" natif n'est pas plus stable
qu'un "oui" ou un "non", il bascule tout autant vers un verdict tranché
qu'un verdict tranché bascule vers lui. L'exclure du vote manquait donc
l'essentiel des bascules réellement observées, sur les deux mesures
successives.

*Conséquence de conception.* Le vote s'applique désormais à toute valeur de
premier verdict, sans exception. Pour "indéterminé"/"non_applicable", cela
signifie qu'une majorité d'avis indépendants en faveur d'un verdict tranché
**remplace** le verdict d'origine plutôt que de le laisser indéterminé par
défaut — un changement de posture par rapport à la version précédente, qui
ne faisait jamais que confirmer ou dégrader vers "indéterminé", jamais
l'inverse. Ce remplacement réutilise toujours la réponse complète d'un avis
qui porte la valeur majoritaire (jamais un mot-clé isolé) et la fait
repasser par la vérification de citation avant publication, pour ne jamais
contourner le principe directeur du moteur (`_verifier_citation`,
factorisée de sorte à être appliquée aussi bien au premier appel qu'à un
avis adopté par vote).

*Conséquences.* Positives : couvre désormais la cause dominante des
bascules mesurées (indéterminé/non_applicable natifs), et peut corriger un
faux indéterminé aussi bien qu'un faux "oui". Négatives : ne couvre pas un
verdict confiant (≥ 0,7) qui se révèle malgré tout instable ; jusqu'à 3
appels au lieu d'1 sur une part désormais plus large des exigences (tout
premier verdict peu sûr, plus seulement oui/partiel/non) ; un verdict
"indéterminé" issu d'une dégradation pour citation invérifiable (confiance
déjà abaissée à ≤ 0,3 par `_ramener_a_indetermine`) repasse lui aussi par le
vote, ce qui lui laisse une chance d'être corrigé si le premier appel avait
cité un passage légèrement reformulé, au prix d'appels supplémentaires sur
un cas qui était auparavant résolu sans coût additionnel.

*Mesure après ce troisième palier.* Même document, deux exécutions, code
identique à ce commit (mesure locale, base de développement, pas encore
vérifiée directement sur Render) : écart de score ramené à **1,4 point**
(65,7 puis 67,1, contre 6,0 puis 7,6 aux deux paliers précédents) et **10
articles sur 40** avec un verdict différent — en net progrès, mais le
résidu observé n'est plus le même phénomène : la majorité de ces 10
bascules ne sont plus des changements de verdict sur un même article, mais
des articles qui **apparaissent ou disparaissent** de la liste des constats
d'une exécution à l'autre (ex. articles 24, 25, 35, 9). Cause identifiée :
`_propagate_dependencies()` reclasse en cascade un article dépendant
("sans objet") quand son article maître l'est déjà (ex. art. 39 dépend de
l'art. 37) ; si le verdict du maître flotte encore d'une exécution à
l'autre — issu d'un cas non couvert par le vote (confiance ≥ 0,7) — ses
dépendants basculent avec lui. Un effet de second ordre du même phénomène
de fond, pas une régression de ce commit ; non traité ici faute de temps
avant le gel du code, à documenter comme limite résiduelle plutôt qu'à
corriger dans l'urgence.

*Réversibilité.* Isolé dans `evaluate_requirement()` et sa fonction
auxiliaire `_verifier_citation()` : retirer le bloc du vote fait retomber
sur le comportement précédent (un seul appel), sans migration ni effet sur
le reste du moteur.

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
| Faux positifs sur documents conformes (DORA, AI Act) | Mesure F2 (`mesure_dora.json`, `mesure_ai_act.json`) : précision de 77,8 % (DORA) et 52,4 % (AI Act) contre un rappel de 100 % et 84,6 % — le moteur exige un niveau de détail assez fin avant d'accepter "conforme", au point de retoquer 7 articles sur 28 du document AI Act conçu comme référence haute | À recalibrer si le mémoire ou la démo s'appuient sur un score de conformité précis pour ces deux référentiels ; sur le RGPD (corpus mesuré depuis plus longtemps, cf. CORPUS.md), la précision est nettement meilleure |
| Exclusion abusive isolée (AI Act, art. 49) | Sur `02_organisme_credit_defaillant.txt`, un déployeur jamais enregistré est classé à tort hors périmètre par le moteur (`mesure_ai_act.json`) — la seule exclusion abusive des 3 mesures F2 (0 sur NIS2 et DORA), probablement une généralisation excessive du ton globalement négatif du document plutôt qu'un effet du filtre d'éligibilité (DA-08) | Non corrigé avant le gel de code (risque de régression non reverifiable à temps) ; à investiguer en priorité si le moteur est retouché après la soutenance |

Ces limites sont documentées volontairement plutôt que masquées : certaines
sont des choix assumés pour l'échelle actuelle du projet, d'autres des
chantiers identifiés mais non engagés faute de priorité.

## 7. Pour aller plus loin

- OWASP Application Security Verification Standard v4.0
- OWASP Cheat Sheet — Authentication, Session Management, Password Storage
- ANSSI, *Recommandations relatives à l'authentification multifacteur*
- Documentation pgvector — indexation HNSW
- CNIL, *Guide de la sécurité des données personnelles*
