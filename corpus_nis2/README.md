# Corpus de validation — NIS2

Squelette vide. Composer ce corpus (documents + vérité terrain) est le
travail de l'équipe, pas de Claude Code — voir la tâche F2 du plan de
soutenance : « Claude Code ne rédige jamais de vérité terrain ni de grille
détaillée pour NIS2/DORA/AI Act ».

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
étroit — voir le tableau de correspondance en tête de ce fichier). Si la
`description` d'un document mentionne le statut de l'organisation, envisager
d'étendre `validation/evaluate.py` pour en extraire `entite_nis2` comme cela
existe déjà pour l'effectif RGPD (`_effectif_depuis_description`) — sans
cela, le filtre répond « à vérifier » plutôt que d'exempter, ce qui reste
correct mais moins représentatif d'un usage réel.

## Une fois le corpus composé

    python -m validation.evaluate --referentiel nis2 --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel nis2 --runs 3 --output rapport_nis2.json   # mesure reelle, necessite GROQ_API_KEY
