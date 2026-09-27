# Corpus de validation — DORA

Composé (4 documents, 89 verdicts annotés) et mesuré en conditions réelles
(Tâche F2, 3 passages/document, `mesure_dora.json` à la racine du dépôt) :
exactitude 91,4 % (IC95 83,9–95,6 %), 0 exclusion abusive, rappel 100 % sur
les manquements. Composé initialement comme brouillon par Claude Code à la
demande explicite de l'équipe (protocole de mesure en plusieurs étapes avec
point de contrôle), puis relu, corrigé et validé par l'équipe avant gel
(`c3bbdc1`) — voir la tâche F2 du plan de soutenance : « Claude Code ne
rédige jamais seul une vérité terrain non revue par l'équipe ».

## Format attendu

Même structure que [`corpus/verite_terrain.json`](../corpus/verite_terrain.json)
(RGPD, voir aussi [`CORPUS.md`](../CORPUS.md) à la racine) :

- un fichier `.txt` par document déposé dans ce dossier ;
- une entrée par document dans `verite_terrain.json`, avec :
  - `fichier` : le nom exact du `.txt` ;
  - `description` : profil de l'organisation en une phrase ;
  - `score_attendu` : `[bas, haut]`, l'intervalle de score jugé correct ;
  - `verdicts_attendus` : `{ "article_ou_groupe": "conforme" | "manquement" | "hors_perimetre" | "tolere" }`,
    uniquement les articles discriminants (pas les 26 obligations auditables
    au complet — voir `app/ingestion/scoping.py::WHITELISTS["dora"]`) ;
  - `jamais_exclure` : les articles de `verdicts_attendus` dont l'exclusion
    serait une faute (obligation réellement due).

Vérifier la structure avant de mesurer quoi que ce soit :

    python -m validation.verifier_verite_terrain --referentiel dora

## Particularité DORA (Tâche F1)

Le filtre d'éligibilité ([`app/services/eligibilite.py`](../backend/app/services/eligibilite.py))
distingue le statut général d'entité financière (la plupart des articles) de
la fourniture de services de paiement (article 23, plus étroit) et des
articles purement institutionnels réservés aux autorités européennes de
surveillance (15, 20, 21 — toujours hors périmètre pour une organisation
cliente, quel que soit son profil). Chaque cas de `verite_terrain.json` fixe
directement `entite_financiere_dora` via un bloc `profil` structuré
(`validation/evaluate.py::_appliquer_profil`), plutôt que de dépendre d'une
extraction heuristique depuis `description` (seule disponible pour
l'effectif RGPD) — le filtre dispose ainsi de la même information qu'un
auditeur lisant le document, sans exemption à tort possible sur une valeur
manquante.

## Résultats de la mesure (Tâche F2)

Voir `mesure_dora.json` à la racine pour le détail complet (métriques,
matrice de confusion, exécution par document). Constats notables signalés à
l'équipe : le moteur penche vers le faux positif sur les documents conformes
(précision 77,8 % pour un rappel de 100 %), avec 8 erreurs concentrées sur
les deux documents censés être les plus conformes ou les plus contrastés —
aucune exclusion abusive en revanche.

## Relancer la mesure (moteur de production)

    python -m validation.evaluate --referentiel dora --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel dora --runs 3 --output rapport_dora.json   # mesure reelle, necessite GROQ_API_KEY

## Ce même corpus mesure aussi le laboratoire (DA-10)

Le laboratoire (`evaluation/`, moteur séparé — DA-07) dispose de sa propre
grille (`referentiel/articles_dora.py`) et réutilise ce même corpus déjà
gelé, via `validation/run_validation.py --referentiel dora` (mesuré en CI,
job `non-regression`). Écart assumé : les articles institutionnels 15, 20
et 21 sont absents de cette grille (le laboratoire n'a pas de mécanisme
d'exemption indépendant du contenu du document, contrairement au filtre
d'éligibilité de production) — voir DA-10, docs/architecture.md.

    python -m validation.run_validation --referentiel dora --corpus corpus_dora --verite corpus_dora/verite_terrain.json --hors-ligne   # verification de bout en bout
    python -m validation.run_validation --referentiel dora --corpus corpus_dora --verite corpus_dora/verite_terrain.json --ci           # mesure reelle, necessite GROQ_API_KEY
