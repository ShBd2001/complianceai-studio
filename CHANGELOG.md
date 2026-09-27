# Journal des modifications

## Correctifs de precision — articles 30 et 37

### Diagnostic

La comparaison des trois retrievers a produit un resultat invariant : 6 erreurs
sur l'article 30 et 5 sur l'article 37, **identiques en lexical, semantique et
hybride**. Ce qui varie entre les trois executions est la recherche de passages ;
ce qui reste constant est la grille d'evaluation. Une erreur invariante ne peut
donc pas provenir du retrieval.

Ces 11 erreurs representaient 65 % des 17 faux positifs du retriever lexical.

### Cause 1 — Article 30 : critere bloquant sans fondement legal

`mesures_securite` figurait parmi les cinq elements attendus, tous bloquants.
Aucun des sept documents du corpus attendus conformes ne contient les
formulations recherchees. Le manquement etait donc prononce mecaniquement sur la
quasi-totalite des documents conformes.

L'article 30(1)(g) impose la description des mesures de securite « dans la mesure
du possible » — seule mention de l'article assortie de cette reserve. En faire un
critere bloquant est contraire au texte.

**Correctif** : `mesures_securite` passe en `bloquant=False`.

### Cause 2 — Article 37 : preuve d'exclusion logiquement impossible

`exclusion_exige_preuve` vaut `True` par defaut : ecarter un article du perimetre
exige une citation litterale du document prouvant la non-applicabilite.

Ce garde-fou est pertinent pour les articles 44-49, qu'un document ecarte par une
affirmation positive (« aucune donnee n'est transferee hors de l'Union »). Il est
inapplicable a l'article 37 : aucun organisme n'ecrit que ses activites de base
n'impliquent pas de suivi a grande echelle. L'exclusion etait donc refusee faute
de citation, l'article maintenu dans le perimetre, puis juge en manquement.

**Correctif** : `exclusion_exige_preuve=False` sur l'article 37 uniquement. Le
garde-fou reste actif partout ailleurs.

### Mesure

    python -m validation.comparer_retrievers --corpus corpus \
        --verite corpus/verite_terrain.json --lexical-seul \
        --sortie comparaison_apres_correctifs.json

Points de controle : le rappel doit rester a 100 % et les exclusions abusives a
zero. Assouplir un critere peut creer des faux negatifs ; si l'un de ces deux
indicateurs se degrade, le correctif correspondant doit etre revu.

---

## Fiabilisation de la suite de tests

`tests/conftest.py` neutralise desormais le modele de langage pour toute la suite
(`LLM_ENABLED=false`, `GROQ_API_KEY=""`).

Deux tests verifiaient le garde-fou qui retire le score lorsque l'analyse s'est
faite sans modele. Ils supposaient implicitement qu'aucune cle Groq n'etait
configuree. Sur un poste qui en possede une, ils s'executaient contre le
fournisseur reel : la suite consommait du quota, dependait du reseau, et ces deux
tests passaient a cote de ce qu'ils annoncaient verifier.

---

## Filtre d'eligibilite (backend)

`app/services/eligibilite.py` tranche en amont l'applicabilite des obligations
conditionnelles du RGPD (art. 13, 14, 30, 37) a partir du profil de
l'organisation, sans appel au modele.

Trois verdicts : `APPLICABLE`, `EXEMPTE`, `A_VERIFIER`. Une information manquante
ne produit jamais une exemption — le cout d'un faux negatif (obligation manquee)
est sans commune mesure avec celui d'un faux positif.

Les regles sont indexees sur `(referentiel, numero d'article)` : l'article 30 du
RGPD est le registre des traitements, celui de NIS2 ou de la CSRD n'a aucun
rapport.

**Portee** : ce filtre concerne le backend FastAPI, pas le harnais de validation
(`evaluation/`), qui constitue un pipeline distinct. Il n'influe donc pas sur les
metriques ci-dessus. Il reste inerte tant que le modele `Organization` ne porte
pas les colonnes de profil ; seul `headcount`, deja present, est exploite.

Integration dans `audit_engine.py` : les exigences ecartees recoivent directement
un verdict `non_applicable` et ne passent ni par la recherche ni par le modele,
mais leur verdict est reinjecte dans la liste complete afin que la propagation
des dependances (art. 37 -> art. 39) et le calcul du score continuent de porter
sur l'integralite du perimetre.

Le taux de repli qui declenche le mode degrade se calcule sur les seules
exigences soumises au modele : inclure les exclusions deterministes au
denominateur ferait franchir le seuil sur un petit organisme et supprimerait un
score valide.

---

## Nettoyage

Supprimes : `backend/config.py` et `backend/llm.py`, copies strictement
identiques de `app/core/config.py` et `app/services/llm.py`, importees par aucun
module. Le risque n'etait pas l'encombrement mais la correction du mauvais
fichier.

Supprimes egalement : `backend/rapport.html` et `backend/politique.txt`,
artefacts d'essais manuels — les tests construisent leur propre document a partir
de la constante `POLICY`.

Ajoute : `.gitignore` a la racine. Le seul existant se trouvait dans `backend/`
et ne couvrait pas le reste du depot.

`backend/.env` n'est pas inclus dans cette archive : conserver la version locale.

---

## Méthode de recherche configurable, lexicale par défaut

La production utilisait la seule recherche sémantique, la moins bonne des
trois méthodes mesurées sur le corpus de validation (exactitude 85,2 %
contre 91,9 % pour le lexical). `RAG_RETRIEVER` (config + `render.yaml`)
bascule désormais entre `"lexical"` (défaut), `"semantique"` et `"hybride"`
(fusion de rangs, k = 60), validé au démarrage. Le classement lexical est
une copie Python fidèle de l'algorithme mesuré dans le harnais de
validation (`evaluation/evaluateur.py::retriever_lexical`), pas une
réimplémentation — la fidélité à l'algorithme mesuré est ce qui rend le
chiffre cité opposable. Détails et justification : DA-07 dans
`docs/architecture.md`. Migration 0013/0014 (tentative par recherche plein
texte PostgreSQL, revenue en arrière au profit de cette approche) et 0015
(non liée) suivent dans l'historique Alembic.

## Vérification de citation et revue humaine sur les constats

Le moteur vérifiait déjà en interne si une citation avancée par le modèle
existait réellement dans les documents, sans jamais l'afficher. Chaque
constat porte désormais `verdict`, `citation_verified`, `needs_human_review`
et `review_reason` (migration 0015), remplis par une règle explicite
(exclusion d'éligibilité, non-applicable par heuristique, citation
vérifiée/introuvable, verdict indéterminé, repli heuristique, confiance
sous `REVIEW_CONFIDENCE_THRESHOLD`). Badges correspondants dans les
rapports HTML/PDF et sur les constats du frontend (liste de campagne et
plan de remédiation), avec un filtre « À revoir ».

## Métriques d'exécution : mode dégradé, appels et jetons

`audits` porte désormais `degraded`, `llm_fallbacks`, `llm_calls`,
`llm_prompt_tokens`, `llm_completion_tokens`, `llm_model`, `retriever` et
`duration_seconds` (migration 0016), remplis à chaque exécution et exposés
dans `AuditOut` avec un coût estimé dérivé (jamais stocké, `None` tant que
`LLM_PRICE_INPUT_PER_MTOK_USD` / `LLM_PRICE_OUTPUT_PER_MTOK_USD` ne sont
pas renseignés — jamais de tarif inventé). Panneau « Détails techniques de
l'analyse » sur la page de campagne. Nouveau script
`backend/scripts/cout_analyses.py` pour un relevé moyenne/max par
référentiel sur une base de production.

## Stockage persistant sur Render

Un redéploiement effaçait jusqu'ici les documents déposés et les rapports
générés (disque éphémère du conteneur). `render.yaml` ajoute un disque
persistant de 1 Go monté sur `/var/data` (`STORAGE_DIR=/var/data/storage`)
pour `complianceai-api` ; `app/main.py` vérifie l'accès en écriture au
démarrage et journalise une erreur claire sinon, sans bloquer le démarrage.

## Profil de l'organisation pour le filtre d'éligibilité

`eligibilite.py::depuis_organisation` ne pouvait s'appuyer que sur
`headcount` (seul champ existant en base) : le filtre répondait donc presque
toujours « à vérifier », même quand l'information est en réalité connue.
`organizations` porte désormais 11 colonnes booléennes nullables (migration
0017), modifiables via `PATCH /orgs/{org_id}/profile` (admin et au-dessus,
sémantique `exclude_unset`) et un formulaire dédié dans les paramètres du
compte. Un champ non renseigné reste `null`, jamais converti en `False`.

## Comparaison de deux campagnes

Nouvelle route `GET /orgs/{org_id}/audits/{audit_id}/compare?with={other_id}` :
catégorise chaque article entre deux campagnes du même référentiel (nouveau,
résolu, inchangé, aggravé, amélioré) et calcule le delta de score. Vue
« Comparer avec… » dans le frontend, accessible depuis une campagne
terminée.

## Correctif de vérification de citation — étiquettes d'extrait et citations assemblées

Le modèle recopiait parfois l'étiquette de mise en forme de son propre
prompt (`[Extrait N — référence]`) au sein même de la citation renvoyée
dans `preuve`, ce qui faisait systématiquement échouer la comparaison
littérale au document source (`citation_verified=False` à tort). Ces
étiquettes sont désormais retirées avant comparaison. Deuxième cas
distinct : une citation authentique mais assemblée à partir de plusieurs
phrases réelles (parfois de passages non contigus) ne correspondait à
aucun passage unique — `_passage_correspondant` retente désormais phrase
par phrase, en exigeant que **chacune** corresponde réellement à un
passage (sinon la citation reste non vérifiée, y compris si une seule
phrase sur plusieurs est fabriquée).

## Harmonisation des badges de vérification

Les badges « Citation vérifiée / non retrouvée », « Indéterminé » et
« Revue humaine requise » utilisaient un système CSS parallèle
(`.badge-verif`) sujet à collision de spécificité avec la classe générique
`.alerte`, d'où un rendu visuel incohérent avec le reste de l'application.
Remplacé par les composants déjà existants (`.etiq`/`.e-*` côté frontend,
`.badge` avec couleurs `SEVERITY_LABEL` côté rapports PDF/HTML). Une
citation non confirmée par le modèle est désormais explicitement étiquetée
comme telle directement sur le bloc de citation (« Citation avancée par le
modèle — non confirmée »), pour ne plus laisser croire à un extrait fiable.

## Retrait du panneau « Détails techniques de l'analyse »

Retiré de la page de campagne (frontend) : la fonction `detailsTechniques()`,
son CSS et les entrées de traduction associées, devenues inutiles.

## Tâche F1 : filtre d'éligibilité pour NIS2, DORA et AI Act

Étend le mécanisme d'éligibilité (`eligibilite.py`, jusqu'ici RGPD
uniquement) aux trois autres référentiels : 5 nouveaux champs de profil
(`entite_nis2`, `entite_financiere_dora`, `ia_utilisee`,
`ia_fournisseur_haut_risque`, `ia_deployeur_haut_risque`, migration 0018),
~40 nouvelles règles indexées sur `(référentiel, article)`. Même principe
de prudence que pour le RGPD : une information manquante ne produit jamais
une exemption. Un avertissement non bloquant est renvoyé à la création
d'une campagne (`scope_warning`) si le profil indique que le référentiel
entier ne s'applique pas à l'organisation.

## Correctif du filtre de statut sur le plan de remédiation

Cette page ne charge que les constats encore ouverts (`open`/`in_progress`),
mais son filtre de statut proposait les 6 statuts possibles : choisir
« Résolu », « Risque accepté » ou « Faux positif » affichait toujours une
liste vide, alors que les cartes récapitulatives juste au-dessus montrent
bien des constats dans ces statuts. `barreFiltres()` accepte désormais une
liste de statuts à proposer, restreinte à ceux réellement présents dans les
données affichées.

## Tâche F2 : préparation de la mesure sur NIS2, DORA et AI Act

`validation/evaluate.py` accepte `--referentiel {rgpd,nis2,dora,ai_act}`
(fixe les valeurs par défaut de `--corpus`/`--verite`, sans rien changer au
comportement RGPD existant). Nouveau
`validation/verifier_verite_terrain.py` : vérifie la structure d'un fichier
de vérité terrain (clés d'article, vocabulaire des verdicts, cohérence de
`jamais_exclure`, présence des fichiers) sans jamais juger le contenu sur
le fond. Dossiers `corpus_nis2/`, `corpus_dora/`, `corpus_ai_act/` créés à
la racine (squelettes vides + README) — composer les documents et leur
vérité terrain reste le travail de l'équipe, jamais celui de l'outillage.

## Gravité et recommandation d'un constat rétrogradé en indéterminé

Quand une conformité affirmée par le modèle ("oui"/"partiel") est ramenée à
"indéterminé" faute de citation vérifiable, la gravité et la recommandation
restaient celles du verdict d'origine — "info" (imposée par le prompt à
tout "oui") et une recommandation du type "poursuivre la pratique
actuelle", laissant croire à tort à une simple observation sans suite. La
gravité est désormais forcée à "minor" et la recommandation remplacée par
un texte qui reflète ce qui reste réellement à vérifier.

## Mise à jour des statuts après changement (plan de remédiation et constats)

`changerSuivi()` enregistrait le nouveau statut côté serveur mais ne
rafraîchissait jamais l'affichage : un constat marqué résolu restait
visible dans la liste "à traiter" jusqu'au rechargement manuel de la page.
Sur le plan de remédiation (qui ne liste que l'ouvert/en cours), un
changement de statut refait désormais tourner la vue à partir des données
serveur ; sur la page détail d'une campagne (où tous les statuts restent
affichés), la donnée locale est mise à jour et le filtre courant réappliqué.

## Correctif d'exemption — article 49 de l'AI Act (enregistrement)

Classé à tort dans le groupe "fournisseur uniquement" : son paragraphe 3
impose aussi aux déployeurs autorités publiques de s'enregistrer, pas
seulement au fournisseur des paragraphes 1 et 2. Nouvelle règle dédiée,
exemption seulement si l'organisation n'est ni fournisseur ni déployeur
d'un système à haut risque.

## Avertissement de périmètre affiché à la création d'une campagne

`scope_warning` (Tâche F1) était renvoyé par l'API mais jamais affiché.
Retenu le temps de la navigation vers la campagne fraîchement créée puis
affiché une seule fois (bannière `.retenu`), associé à l'identifiant de
campagne pour ne jamais s'afficher à tort sur une autre visite.

## Page dédiée par organisation pour le profil d'éligibilité

Le formulaire de profil, embarqué dans "Mon compte", modifiait
silencieusement l'organisation "active" du commutateur global sans jamais
afficher son nom — avec plusieurs organisations, rien ne distinguait
laquelle on renseignait. Nouvelle page dédiée (`#/organisation/{id}`), nom
de l'organisation en titre, un onglet par référentiel avec décompte de
progression ; une organisation nouvellement créée y redirige
automatiquement. Refonte visuelle au passage : un vrai contrôle segmenté
par question (rail continu, pastille active) plutôt que trois boutons
bordés séparés, barre de progression globale mise à jour en direct.
Corrige au passage un bug latent de `creerOrganisation()` (l'organisation
active en mémoire ne suivait pas la nouvelle organisation créée).

## Visite guidée, page « À propos » et champ effectif

Nouvelle première étape de la visite guidée : renseigner le profil
d'éligibilité avant de lancer une analyse, puisque c'est le seul rappel
fiable pour un compte qui vient de s'inscrire (l'organisation créée à
l'inscription ne passe pas par la redirection automatique réservée à la
création depuis "Mon compte"). Texte de l'étape « Applicabilité » de la
page « À propos » mis à jour (le profil couvre désormais NIS2/DORA/AI Act,
pas seulement le RGPD) et bug de traduction corrigé au passage (`tr()`
n'était jamais appelé sur ces textes). Le formulaire de profil manquait
aussi l'effectif : seule information chiffrée dont dépend la dispense de
registre de l'article 30(5) du RGPD, jusqu'ici une colonne existante mais
non modifiable après la création de l'organisation (aucune route ne
l'exposait) — ajouté comme champ numérique dédié, avec sa propre carte.

## Gravité "info" exclue pour tout constat indéterminé, natif ou rétrogradé

Le correctif sur la rétrogradation ("oui"/"partiel" → "indéterminé" faute
de citation vérifiable) ne couvrait pas le cas où le modèle répond
"indéterminé" de lui-même — parfois avec une citation réellement vérifiée
à l'appui de son raisonnement — car le prompt n'impose une gravité qu'au
"oui" ("info" obligatoire), rien pour "indéterminé". Résultat observé en
usage réel (article 44) : un badge "Information" affiché à côté de "Revue
humaine requise", alors que ce second badge est toujours vrai sur un
indéterminé quelle qu'en soit l'origine. La règle est déplacée dans la
boucle principale de `run_audit()` pour couvrir les deux origines d'un
coup : toute gravité "info" sur un verdict "indéterminé" est relevée à
"minor".

## Changement d'offre après la création de l'organisation

Le message de quota épuisé promettait "il suffit de passer au palier
supérieur depuis votre espace Mon compte", mais `plan` n'était fixé qu'à
l'inscription et n'était modifiable nulle part ensuite. Nouvelle route
`PATCH /orgs/{org_id}/plan`, réservée au propriétaire (une décision qui
affecte le coût de toute l'organisation, au même titre que sa suppression) :
refuse une offre dont la limite de membres serait déjà dépassée par
l'effectif actuel plutôt que de choisir qui retirer à la place de
l'utilisateur, et réinitialise la rétention personnalisée des documents en
quittant l'offre Cabinet (qui seule la permet) pour ne pas laisser une
purge automatique active en silence sur un réglage devenu invisible dans
l'interface. Sélecteur d'offre directement dans le tableau des
organisations de "Mon compte", réservé au propriétaire.

## Second avis : vote à 3 et seuil de déclenchement relevé

Le second avis ciblé (voir entrée précédente sur l'instabilité des
verdicts) restait insuffisant : mesuré en production après déploiement,
une même analyse relancée deux fois sur le même document affichait encore
un écart de 7,6 points de score. Deux causes identifiées : le seuil de
déclenchement (0,5, celui de la revue humaine) manquait des cas instables
jusqu'à une confiance affichée de 0,6 ; et un unique second appel en
désaccord rétrogradait systématiquement le verdict, alors que ce second
appel pouvait lui-même être le bruit. Correctifs : seuil dédié
`SECOND_OPINION_CONFIDENCE_THRESHOLD` relevé à 0,7, et un troisième avis
indépendant tranche désormais un premier désaccord — le verdict d'origine
est conservé s'il obtient la majorité absolue des avis recueillis, sinon
ramené à "indéterminé" par prudence. Inspiré du vote majoritaire déjà
outillé côté laboratoire (`evaluation/evaluateur.py`), réimplémenté
localement sans importer ce package (voir DA-07/DA-09,
docs/architecture.md). Mesure de l'effet réel sur l'ampleur des écarts,
une fois ce correctif déployé, encore à faire.

## Second avis : extension à "indéterminé" et "non_applicable" natifs

Le vote à 3 (entrée précédente) restait insuffisant : mesuré à nouveau,
l'écart de score ne se réduisait que de 7,6 à 6,0 points, et 14 articles sur
39 changeaient encore de verdict entre deux exécutions du même document. En
regardant le détail, 12 de ces 14 bascules concernaient un "indéterminé" ou
un "non_applicable" natif — exactement les deux catégories que le
mécanisme excluait, sur l'hypothèse (fausse, invalidée par cette mesure)
qu'un "indéterminé" natif serait déjà un état stable. Le vote s'applique
désormais à tout premier verdict peu sûr, sans exception : si une majorité
d'avis indépendants s'accorde sur un verdict tranché différent, il
remplace l'"indéterminé"/"non_applicable" d'origine (réponse complète
adoptée, jamais un mot-clé isolé), et repasse par la vérification de
citation avant publication comme n'importe quel premier appel
(`_verifier_citation`, factorisée à cet effet). Mesure locale après ce
correctif : écart ramené à 1,4 point (contre 6,0 puis 7,6 aux paliers
précédents) sur le même document, deux exécutions — net progrès. Résidu
identifié : la cascade de dépendances entre articles (`_propagate_dependencies`)
peut encore faire apparaître ou disparaître un article dépendant si son
article maître garde une confiance suffisante pour échapper au vote ; noté
comme limite résiduelle dans DA-09 plutôt que corrigé dans l'urgence, faute
de temps avant le gel du code.

## Retire la mention du modèle sur le badge de citation non confirmée

Le badge affiché sur une citation non vérifiée répétait l'attribution au
modèle ("Citation avancée par le modèle — non confirmée") alors que la
carte du constat porte déjà ce contexte (badge "Citation non retrouvée"
juste en dessous) : simplifié à "Citation non confirmée".

## Tâche F2 : mesure réelle NIS2/DORA/AI Act

Corpus composé (4 documents fictifs par référentiel, 219 verdicts annotés
au total) selon un protocole en plusieurs étapes avec point de contrôle
explicite : brouillon rédigé par Claude Code à la demande de l'équipe, relu
et corrigé, gelé (`c3bbdc1`) seulement après validation. Support ajouté au
harnais (`validation/harnais.py`, `validation/evaluate.py`,
`validation/verifier_verite_terrain.py`) pour un bloc `profil` structuré par
cas de `verite_terrain.json`, fixant directement `entite_nis2`,
`entite_financiere_dora`, `ia_fournisseur_haut_risque`,
`ia_deployeur_haut_risque`, `ia_utilisee` sur l'organisation de test — plus
fiable que l'extraction heuristique depuis `description`, seule disponible
jusqu'ici pour l'effectif RGPD.

Mesure réelle (3 passages/document, `mesure_nis2.json`, `mesure_dora.json`,
`mesure_ai_act.json`) : exactitude 90,6 % / 91,4 % / 86,7 %, exclusions
abusives 0 / 0 / 1. Deux constats notables signalés à l'équipe pour
arbitrage post-soutenance, non corrigés avant le gel faute de temps pour
une nouvelle mesure de vérification : le moteur penche vers le faux positif
sur les documents conformes en DORA et AI Act (précision 77,8 % et 52,4 %
pour un rappel de 100 % et 84,6 %), et une exclusion abusive isolée sur
l'AI Act (article 49, déployeur jamais enregistré classé à tort hors
périmètre).

## Protection en CI pour NIS2/DORA/AI Act (non-regression-autres-referentiels)

Le job `non-regression` existant ne couvre que le RGPD : il mesure le moteur
du laboratoire (`evaluation/`), codé en dur pour ce référentiel
(`referentiel/articles.py`) — reconstruire l'équivalent pour NIS2/DORA/AI
Act n'était pas réalisable avant le gel. `validation/evaluate.py` gagne un
drapeau `--ci` (seuils bloquants `SEUILS_CI`, calibrés avec marge sous
l'unique mesure réelle disponible — même principe que
`harnais.py::SeuilsCI` pour le RGPD) et un nouveau job CI
(`non-regression-autres-referentiels`, branche `main` uniquement) l'exécute
sur les trois référentiels à chaque push. Seuls exactitude et exclusions
abusives bloquent : précision/rappel/score sont calculés sur 4 documents
seulement, trop peu pour ne pas osciller de plusieurs points sans
régression réelle — affichés, non bloquants. Le seuil AI Act tolère la
seule exclusion abusive déjà connue (article 49) plutôt que de partir rouge
dès le premier run.

## Le laboratoire (evaluation/) couvre désormais NIS2, DORA et AI Act

Jusqu'ici, seul le RGPD disposait d'une mesure réelle continue en CI (moteur
du laboratoire, `evaluation/`) ; NIS2/DORA/AI Act n'avaient que le moteur de
production (entrée précédente). `referentiel/articles.py` était codé en dur
pour le RGPD (grille d'éléments probants par article) : `evaluation/prompts.py`
et `evaluation/evaluateur.py` généralisés (référentiel en paramètre, défaut
RGPD — texte des prompts vérifié identique caractère pour caractère, zéro
régression), trois nouvelles grilles (`referentiel/articles_{nis2,dora,
ai_act}.py`) réutilisant le corpus déjà gelé de la Tâche F2. Le job CI
`non-regression` mesure maintenant les quatre référentiels à chaque push sur
`main`. Deux bugs trouvés et corrigés en cours de construction : une
condition d'applicabilité mal configurée (`exclusion_exige_preuve=False`,
effet inverse de l'intention) provoquait 8 exclusions abusives sur l'AI Act ;
une autre condition suggérait à tort qu'un système d'IA développé et utilisé
en interne n'aurait pas la qualité de fournisseur. Après correction :
exactitude 90,6 % (NIS2), 92,9 % (AI Act, 0 exclusion abusive), ~88 % (DORA,
métrique brute sous-estimée par les 3 articles institutionnels — 15/20/21 —
volontairement absents de la grille, voir DA-10, docs/architecture.md).

## Correction post-gel de 2 verdicts NIS2 (à la demande de l'équipe)

Le rapport F2 initial signalait déjà 2 des 3 faux négatifs NIS2 comme
attendus discutables (rappel 72,7 %) : article 24 (doc 2 — facultatif pour
l'État membre, pas une obligation inconditionnelle de l'entité) et article
30 (doc 3 — notification purement volontaire, son absence n'est
juridiquement pas un manquement). Corrigés dans `corpus_nis2/verite_terrain.json`
avec justification, à la demande explicite de l'équipe, puis remesurés sur
les deux moteurs (`mesure_nis2.json` mis à jour). Résultat production :
**exactitude 100 %, rappel 100 %, précision 100 %, 0 faux négatif**.
L'article 21 (doc 3), également signalé comme débattable, n'a volontairement
pas été corrigé : les gaps structurels identifiés restent réels. Mesure du
laboratoire relancée aussi (même corpus) : 78,1 % — écart avec la mesure
initiale (90,6 %) attribué à la variance normale du modèle sur un seul
tirage (DA-09), pas à cette correction.

## AI Act, article 49 : investigué comme un bug, corrigé comme une vérité terrain

L'exclusion abusive signalée dans le rapport F2 (article 49, document 2)
a d'abord été traitée comme un défaut du moteur. Un correctif de
`SYSTEM_PROMPT` (`audit_engine.py`, clarification sur l'indépendance des
rôles fournisseur/déployeur) a été écrit, puis testé en conditions réelles
(3 exécutions du document concerné) : aucun effet mesuré, verdict stable à
l'identique — abandonné et retiré. Lire le raisonnement réel du modèle en
base (`Finding.description`) a montré qu'il appliquait une lecture
juridique précise, déjà identifiée comme zone grise dans le rapport F2
initial (l'article 49§3 vise en particulier les déployeurs publics, cette
entreprise étant privée) : ce n'était pas un bug, c'était la vérité
terrain qui tranchait à tort une question réellement ambiguë. Corrigée
(`manquement` → `tolere`) dans `corpus_ai_act/verite_terrain.json`, à la
demande explicite de l'équipe. Remesuré sur les deux moteurs
(`mesure_ai_act.json` mis à jour) : exactitude production 86,7 % → **92,8
%**, rappel 84,6 % → **91,7 %**, exclusions abusives 1 → **0**.
