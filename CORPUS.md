# Corpus de validation — 15 documents, 210 verdicts

## Ce que le corpus couvre

| # | Document | Profil | Ce qu'il teste |
|---|---|---|---|
| 01 | Grande PME distribution | 610 salariés, gouvernance mature | Référence haute : le moteur doit reconnaître une conformité réelle |
| 02 | Micro-entreprise boulangerie | 2 salariés, mentions légales seules | Référence basse : manquements massifs |
| 03 | PME artisanale menuiserie | 34 salariés, sécurité solide | Sécurité forte ≠ formalisation (art. 12, 30, 33) |
| 04 | Atelier de reliure | 2 personnes, minimal mais correct | Petite structure conforme + exclusions légitimes prouvées |
| 05 | Cabinet médical | Données de santé, transferts | **9(2)(h)** : santé licite. Transferts non encadrés |
| 06 | RH industrie | 340 salariés, données sensibles | **9(2)(b)** : droit du travail. Art. 22 en manquement réel |
| 07 | Cabinet de conseil | Affirme la conformité | **Contradictoire** : chaque détail dément le préambule |
| 08 | Organisme de formation | Registre incomplet | **Crédit partiel** : art. 30 existant mais lacunaire |
| 09 | E-commerce régional | Transferts hors UE encadrés | **Piège inverse** : transfert licite ≠ manquement |
| 10 | Éditeur B2B | Fichiers achetés, sources publiques | **Art. 14** : collecte indirecte, applicable et conforme |
| 11 | Centre commercial | 187 caméras, 28 000 visiteurs/jour | DPO et AIPD obligatoires **et présents** |
| 12 | Courtier en crédit | Scoring automatique, rejet immédiat | **Art. 22 applicable ET conforme** — le cas le plus exigeant |
| 13 | Association de quartier | Faible maturité, certificats médicaux | **Inverse du 05** : santé sans fondement 9(2) |
| 14 | Réseau hôtelier | 780 salariés, 217 lignes | Chunking sur document long |
| 15 | Agence marketing | Sécurité exemplaire, reste absent | **Piège central 32 vs 33** |

## Répartition

- **115 conformes** (55 %), **81 manquements** (39 %), **14 hors périmètre** (7 %)
- **18 articles** couverts, **108 obligations protégées** par `jamais_exclure`

Le déséquilibre vers la conformité est délibéré : le corpus d'origine ne contenait que des documents médiocres, ce qui favorise mécaniquement un moteur trop sévère. Les documents 01, 04, 09, 10, 11, 12 et 14 pénalisent les faux positifs.

## Les pièges, et pourquoi ils existent

**Symétrie sur les données de santé.** Le document 05 (cabinet médical, licite au 9(2)(h)) et le 13 (association, illicite faute de fondement) empêchent le moteur de retenir une règle simpliste dans un sens comme dans l'autre.

**Symétrie sur l'article 22.** Le 06 est en manquement (rejet automatique sans revue), le 11 est hors périmètre (revue humaine effective), le 12 est conforme (applicable avec toutes les garanties). Trois issues différentes pour le même article.

**Symétrie sur les transferts.** Le 05 et le 07 sont en manquement, le 09 et le 14 sont conformes avec CCT datées. Un transfert hors UE n'est pas un manquement en soi.

**Le piège 32 contre 33.** Le document 15 décrit une sécurité irréprochable sur dix lignes et conclut « le risque est réduit au minimum ». Aucune procédure de notification. C'est la version aggravée de l'erreur d'origine du moteur.

## Attendu

Seuils bloquants : rappel ≥ 90 %, précision ≥ 95 %, exactitude ≥ 90 %, **exclusions abusives = 0**.

Avec 210 verdicts, l'intervalle de confiance passe sous 10 points — les métriques deviennent exploitables, ce qui n'était pas le cas sur 25.

## Avertissement de méthode

La grille du référentiel a été ajustée en observant les documents 03 et 05. Les treize autres n'ont jamais servi à cet ajustement : **ce sont eux qui portent la valeur probante du corpus**. Si les résultats s'effondrent sur les nouveaux documents, c'est que les corrections précédentes étaient du surajustement, et il faudra le savoir.
