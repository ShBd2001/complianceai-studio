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
