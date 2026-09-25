# Corpus de validation — AI Act

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
de profil dédié n'existe, ils sont donc toujours évalués. Si la
`description` d'un document mentionne le rôle de l'organisation, envisager
d'étendre `validation/evaluate.py` pour en extraire `ia_utilisee` /
`ia_fournisseur_haut_risque` / `ia_deployeur_haut_risque` comme cela existe
déjà pour l'effectif RGPD (`_effectif_depuis_description`) — sans cela, le
filtre répond « à vérifier » plutôt que d'exempter, ce qui reste correct
mais moins représentatif d'un usage réel.

## Une fois le corpus composé

    python -m validation.evaluate --referentiel ai_act --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel ai_act --runs 3 --output rapport_ai_act.json   # mesure reelle, necessite GROQ_API_KEY
