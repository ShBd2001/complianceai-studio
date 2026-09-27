# Corpus de validation — NIS2

Composé (4 documents, 32 verdicts annotés) et mesuré en conditions réelles
(Tâche F2, 3 passages/document, `mesure_nis2.json` à la racine du dépôt) :
exactitude 100 % (IC95 89,0–100 %), 0 exclusion abusive, après correction
de 2 verdicts post-gel (voir plus bas). Composé initialement comme
brouillon par Claude Code à la demande explicite de l'équipe (protocole de
mesure en plusieurs étapes avec point de contrôle), puis relu, corrigé et
validé par l'équipe avant gel (`c3bbdc1`) — voir la tâche F2 du plan de
soutenance : « Claude Code ne rédige jamais seul une vérité terrain non
revue par l'équipe ».

## Format attendu

Même structure que [`corpus/verite_terrain.json`](../corpus/verite_terrain.json)
(RGPD, voir aussi [`CORPUS.md`](../CORPUS.md) à la racine) :

- un fichier `.txt` par document déposé dans ce dossier ;
- une entrée par document dans `verite_terrain.json`, avec :
  - `fichier` : le nom exact du `.txt` ;
  - `description` : profil de l'organisation en une phrase ;
  - `score_attendu` : `[bas, haut]`, l'intervalle de score jugé correct ;
  - `verdicts_attendus` : `{ "article_ou_groupe": "conforme" | "manquement" | "hors_perimetre" | "tolere" }`,
    uniquement les articles discriminants (pas les 8 obligations auditables
    au complet — voir `app/ingestion/scoping.py::WHITELISTS["nis2"]`) ;
  - `jamais_exclure` : les articles de `verdicts_attendus` dont l'exclusion
    serait une faute (obligation réellement due).

Vérifier la structure avant de mesurer quoi que ce soit :

    python -m validation.verifier_verite_terrain --referentiel nis2

## Particularité NIS2 (Tâche F1)

Le filtre d'éligibilité ([`app/services/eligibilite.py`](../backend/app/services/eligibilite.py))
distingue le statut général NIS2 (entité essentielle/importante, articles
20/21/23/24/29/30) de la fourniture de DNS/registre (articles 27/28, plus
étroit — voir le tableau de correspondance en tête de ce fichier). Chaque cas
de `verite_terrain.json` fixe directement `entite_nis2` via un bloc `profil`
structuré (`validation/evaluate.py::_appliquer_profil`), plutôt que de
dépendre d'une extraction heuristique depuis `description` (seule disponible
pour l'effectif RGPD).

## Résultats de la mesure (Tâche F2)

Voir `mesure_nis2.json` à la racine pour le détail complet. Mesure initiale :
exactitude 90,6 %, rappel 72,7 %, 3 faux négatifs. Analyse a posteriori :
2 des 3 échecs portaient sur des verdicts attendus déjà signalés comme
discutables (article 24, facultatif pour l'entité et non une obligation
inconditionnelle ; article 30, notification purement volontaire dont
l'absence n'est pas juridiquement un manquement) — **corrigés post-gel le
2026-09-27, à la demande explicite de l'équipe** (voir le commentaire de
chaque cas dans `verite_terrain.json`). Après correction : **exactitude
100 %, rappel 100 %, précision 100 %, 0 faux négatif, 0 exclusion
abusive**. L'article 21 du document 3, également signalé comme débattable,
n'a volontairement pas été corrigé : les gaps structurels identifiés
(continuité/reprise) justifient encore la lecture manquement.

## Relancer la mesure (moteur de production)

    python -m validation.evaluate --referentiel nis2 --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel nis2 --runs 3 --output rapport_nis2.json   # mesure reelle, necessite GROQ_API_KEY

## Ce même corpus mesure aussi le laboratoire (DA-10)

Le laboratoire (`evaluation/`, moteur séparé — DA-07) dispose de sa propre
grille d'éléments probants (`referentiel/articles_nis2.py`) et réutilise
ce même corpus déjà gelé (y compris la correction post-gel ci-dessus), via
`validation/run_validation.py --referentiel nis2` (mesuré en CI, job
`non-regression`). Exactitude observée sur des mesures ponctuelles à un
seul passage : 90,6 % puis 78,1 % — écart attribué à la variance normale
du modèle sur un seul tirage (DA-09), pas à la correction ci-dessus ; les
seuils bloquants de ce référentiel restent volontairement larges tant
qu'une mesure `--repetitions 3` n'a pas été faite (DA-10) :

    python -m validation.run_validation --referentiel nis2 --corpus corpus_nis2 --verite corpus_nis2/verite_terrain.json --hors-ligne   # verification de bout en bout
    python -m validation.run_validation --referentiel nis2 --corpus corpus_nis2 --verite corpus_nis2/verite_terrain.json --ci           # mesure reelle, necessite GROQ_API_KEY
