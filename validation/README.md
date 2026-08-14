# Corpus de validation

Ce dossier repond a une seule question : **comment savons-nous que le moteur
a raison ?**

Sans reponse chiffree, un outil d'audit reste une opinion automatisee. Le
corpus fournit des documents dont la conformite est connue a l'avance, et le
harnais mesure l'ecart entre ce que le moteur affirme et cette verite terrain.

## Contenu

| Fichier | Profil | Score attendu |
|---|---|---|
| `01_conforme.txt` | Grande PME structuree, DPO, registre, procedures | 85-100 |
| `02_defaillant.txt` | Micro-entreprise, politique minimale | 0-30 |
| `03_intermediaire.txt` | PME correcte sur la securite, lacunaire ailleurs | 55-80 |
| `04_hors_perimetre.txt` | Artisan, traitements tres limites | 70-100 |
| `05_sensible.txt` | Cabinet medical, donnees de sante, transferts | 40-70 |

Chaque document a son annotation dans `annotations.json` : pour les articles
discriminants, le verdict attendu d'un auditeur humain.

## Lancer la mesure

    python -m validation.evaluate

Options :

    --runs 3          nombre de passages par document (mesure de variance)
    --only 01 03      restreindre a certains documents
    --output rapport.json

## Metriques produites

**Justesse.** Precision, rappel et F1 sur la detection des non-conformites,
plus le taux d'exclusions correctes. Une exclusion abusive est un faux negatif
grave : elle fait disparaitre une obligation reelle du rapport.

**Ecart de score.** Erreur absolue moyenne entre le score annonce et
l'intervalle attendu.

**Reproductibilite.** Sur plusieurs passages du meme document : proportion
d'articles au verdict stable, et ecart-type du score.

## Limites assumees

Cinq documents ne constituent pas un echantillon statistique. Ils sont ecrits
pour couvrir des profils contrastes, pas pour representer la population des
entreprises francaises. Les annotations refletent une lecture argumentee du
RGPD, pas une decision de justice : certaines sont discutables et le fichier
d'annotation porte le motif de chaque choix.

L'objectif est de detecter les regressions et de disposer de chiffres
defendables, pas de prouver une exactitude absolue.
