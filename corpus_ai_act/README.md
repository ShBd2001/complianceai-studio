# Corpus de validation — AI Act

Composé (4 documents, 98 verdicts annotés) et mesuré en conditions réelles
(Tâche F2, 3 passages/document, `mesure_ai_act.json` à la racine du dépôt) :
exactitude 96,9 %, précision 100 %, rappel 100 %, 0 exclusion abusive,
après correction d'un verdict post-gel et de deux problèmes distincts sur
les articles composés de plusieurs sous-points légaux (voir plus bas).
Composé initialement comme brouillon
par Claude Code à la demande explicite de l'équipe (protocole de mesure en
plusieurs étapes avec point de contrôle), puis relu, corrigé et validé par
l'équipe avant gel (`c3bbdc1`) — voir la tâche F2 du plan de soutenance :
« Claude Code ne rédige jamais seul une vérité terrain non revue par
l'équipe ».

## Format attendu

Même structure que [`corpus/verite_terrain.json`](../corpus/verite_terrain.json)
(RGPD, voir aussi [`CORPUS.md`](../CORPUS.md) à la racine) :

- un fichier `.txt` par document déposé dans ce dossier ;
- une entrée par document dans `verite_terrain.json`, avec :
  - `fichier` : le nom exact du `.txt` ;
  - `description` : profil de l'organisation en une phrase ;
  - `score_attendu` : `[bas, haut]`, l'intervalle de score jugé correct ;
  - `verdicts_attendus` : `{ "article_ou_groupe": "conforme" | "manquement" | "hors_perimetre" | "tolere" }`,
    uniquement les articles discriminants (pas les 28 obligations auditables
    au complet — voir `app/ingestion/scoping.py::WHITELISTS["ai_act"]`) ;
  - `jamais_exclure` : les articles de `verdicts_attendus` dont l'exclusion
    serait une faute (obligation réellement due).

Vérifier la structure avant de mesurer quoi que ce soit :

    python -m validation.verifier_verite_terrain --referentiel ai_act

## Particularité AI Act (Tâche F1)

Le filtre d'éligibilité ([`app/services/eligibilite.py`](../backend/app/services/eligibilite.py))
distingue quatre profils : l'article 5 (pratiques interdites) s'applique
toujours, sans exemption possible ; les articles 8 à 22 (plus 25, 47-49, 72,
73) ne concernent que les fournisseurs de systèmes à haut risque ; l'article
50 (transparence) ne dépend que de l'usage d'un système d'IA, quel qu'il
soit ; les articles 26/27/86 (obligations du déployeur) sont plus étroits
que la simple qualité de déployeur. Les articles 23/24 (importateurs/
distributeurs) n'ont volontairement aucune règle d'exemption : aucun champ
de profil dédié n'existe, ils sont donc toujours évalués. Chaque cas de
`verite_terrain.json` fixe directement `ia_utilisee` / `ia_fournisseur_haut_risque`
/ `ia_deployeur_haut_risque` via un bloc `profil` structuré
(`validation/evaluate.py::_appliquer_profil`), plutôt que de dépendre d'une
extraction heuristique depuis `description` (seule disponible pour
l'effectif RGPD).

## Résultats de la mesure (Tâche F2)

Voir `mesure_ai_act.json` à la racine pour le détail complet. Mesure
initiale : exactitude 86,7 %, 1 exclusion abusive (article 49, document 2 —
enregistrement d'un déployeur jamais enregistré, classé à tort hors
périmètre). Investigation approfondie (lecture du raisonnement réel du
modèle en base, pas une simple relecture) : le modèle applique en fait une
lecture juridique précise et cohérente (l'article 49§3 vise en particulier
les déployeurs **publics**, cette entreprise étant privée) — exactement la
nuance déjà signalée comme zone grise dans le rapport F2 initial. Un
correctif de prompt (`SYSTEM_PROMPT`, `audit_engine.py`) a été tenté, testé
en conditions réelles sur 3 exécutions, puis **abandonné** car sans effet
mesuré (le verdict restait stable, ce n'était donc pas un bug de
raisonnement à corriger par le prompt). **Corrigé plutôt dans la référence**
(manquement → `tolere`, à la demande explicite de l'équipe, 2026-09-27) —
voir le commentaire du cas dans `verite_terrain.json` pour le détail
complet. Après correction : **exactitude 92,8 %, rappel 91,7 %, 0 exclusion
abusive**. Le document censé être le plus conforme (01) concentrait alors
la majorité des faux positifs, signe que le moteur exigeait un niveau de
détail assez fin avant d'accepter "conforme" pour les articles composés de
plusieurs sous-points légaux.

**Corrigé le 2026-09-30 et le 2026-10-01** (voir CHANGELOG.md pour le
détail complet des deux correctifs) : `app/ingestion/exigences_simplifiees.py`
remplace le texte légal brut par une formulation globale (comme le fait
le laboratoire) à la fois pour la question posée au modèle et pour la
requête de recherche de passages — cette seconde partie s'est révélée
nécessaire après diagnostic direct (un passage pourtant explicite dans le
document n'était simplement jamais retrouvé). Effet de bord trouvé et
corrigé au passage : les articles 12 et 49 partagent le même intitulé
légal "Enregistrement", source d'une confusion réelle du modèle. Mesure
finale : **exactitude 96,9 %, précision 100 %, rappel 100 %, 0 exclusion
abusive**. 3 erreurs résiduelles sur 97 constats, toutes de même nature
bénigne (articles 23/24, hors périmètre classé à tort conforme — n'affecte
ni la précision ni le rappel).

## Relancer la mesure (moteur de production)

    python -m validation.evaluate --referentiel ai_act --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel ai_act --runs 3 --output rapport_ai_act.json   # mesure reelle, necessite GROQ_API_KEY

## Ce même corpus mesure aussi le laboratoire (DA-10)

Le laboratoire (`evaluation/`, moteur séparé — DA-07) dispose de sa propre
grille (`referentiel/articles_ai_act.py`) et réutilise ce même corpus déjà
gelé (y compris la correction post-gel ci-dessus), via
`validation/run_validation.py --referentiel ai_act` (mesuré en CI, job
`non-regression`). Après correction de deux erreurs de condition
d'applicabilité trouvées en cours de construction (voir DA-10,
docs/architecture.md) : exactitude entre 90,8 % et 92,9 % selon le tirage
(mesures ponctuelles à un seul passage — variance normale du modèle,
DA-09), 0 exclusion abusive, rappel 100 % sur les manquements dans les deux
mesures. **Mesure rigoureuse à 3 passages faite le 2026-10-01**
(`rapport_labo_ai_act.json`) : exactitude 91,8 %, précision 60,0 %, rappel
100 %, 0 exclusion abusive — nettement en dessous du moteur de production
sur ce référentiel (96,9 %/100 %/100 %, voir README.md racine et le
correctif du 2026-10-01 ci-dessus) : contrairement à RGPD, la production
dépasse maintenant le laboratoire sur AI Act.

    python -m validation.run_validation --referentiel ai_act --corpus corpus_ai_act --verite corpus_ai_act/verite_terrain.json --hors-ligne   # verification de bout en bout
    python -m validation.run_validation --referentiel ai_act --corpus corpus_ai_act --verite corpus_ai_act/verite_terrain.json --ci           # mesure reelle, necessite GROQ_API_KEY
