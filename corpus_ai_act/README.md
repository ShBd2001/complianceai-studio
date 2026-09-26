# Corpus de validation — AI Act

Composé (4 documents, 98 verdicts annotés) et mesuré en conditions réelles
(Tâche F2, 3 passages/document, `mesure_ai_act.json` à la racine du dépôt) :
exactitude 86,7 % (IC95 78,6–92,1 %), 1 exclusion abusive (article 49).
Composé initialement comme brouillon par Claude Code à la demande explicite
de l'équipe (protocole de mesure en plusieurs étapes avec point de
contrôle), puis relu, corrigé et validé par l'équipe avant gel (`c3bbdc1`)
— voir la tâche F2 du plan de soutenance : « Claude Code ne rédige jamais
seul une vérité terrain non revue par l'équipe ».

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

Voir `mesure_ai_act.json` à la racine pour le détail complet. Constat le
plus notable : une exclusion abusive sur l'article 49 (document 2, obligation
d'enregistrement d'un déployeur jamais enregistré, classée à tort hors
périmètre par le moteur) — le seul cas des trois référentiels. Le document
censé être le plus conforme (01) concentre 7 des 13 erreurs, toutes des faux
positifs, signe que le moteur exige un niveau de détail assez fin avant
d'accepter "conforme".

## Relancer la mesure

    python -m validation.evaluate --referentiel ai_act --sans-modele    # verification de bout en bout, resultats non valides
    python -m validation.evaluate --referentiel ai_act --runs 3 --output rapport_ai_act.json   # mesure reelle, necessite GROQ_API_KEY
