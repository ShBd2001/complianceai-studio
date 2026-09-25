# Corpus de validation — DORA

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
cliente, quel que soit son profil). Si la `description` d'un document
mentionne le statut de l'organisation, envisager d'étendre
`validation/evaluate.py` pour en extraire `entite_financiere_dora` comme
cela existe déjà pour l'effectif RGPD (`_effectif_depuis_description`) —
sans cela, le filtre répond « à vérifier » plutôt que d'exempter, ce qui
reste correct mais moins représentatif d'un usage réel.

## Une fois le corpus composé

    python -m validation.evaluate --referentiel dora --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel dora --runs 3 --output rapport_dora.json   # mesure reelle, necessite GROQ_API_KEY
