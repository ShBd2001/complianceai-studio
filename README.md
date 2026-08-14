# Moteur d'audit RGPD — refonte v2

Module autonome à câbler dans le backend FastAPI existant. Il remplace la chaîne
d'évaluation, pas l'application.

## Le diagnostic en une phrase

Les six faux négatifs du run précédent portaient sur les articles 12, 30 et 33 —
soit des obligations dont le manquement est une **absence**. Un modèle raisonne
sur ce qui est écrit, pas sur ce qui manque : il lisait une politique de sécurité
solide et en déduisait une maturité générale. La correction n'est pas un réglage
de prompt, c'est un renversement de la charge de la preuve.

## Ce qui change

| Avant | Maintenant |
|---|---|
| 1 appel pour 17 articles sur le document entier | 1 appel par article, sur les passages retrouvés |
| Le modèle rend le verdict | Le modèle extrait des preuves, le code rend le verdict |
| Conforme par défaut, en pratique | **Manquement par défaut**, conforme sur preuve seulement |
| Anti-fabrication : consigne dans le prompt | Vérification mécanique des citations contre le texte source |
| Article 9 indexé en bloc | Les 10 dérogations du 9(2) sont des passages distincts |
| Aucune passe dérogation | Passe obligatoire avant tout manquement sur un article dérogeable |
| Score opaque | Formule pondérée, explicable ligne par ligne |
| 1 passage par document | Découpage ~500 tokens, recouvrement 15 %, frontières de sections |

## Arborescence

```
referentiel/articles.py       18 articles × éléments probants, dérogations, criticité
rag/chunking.py               découpage par sections avec recouvrement
evaluation/prompts.py         les 3 passes : applicabilité, extraction, dérogation
evaluation/verificateur.py    vérification mécanique des citations
evaluation/evaluateur.py      orchestration, verdict par défaut = manquement
evaluation/scoring.py         score pondéré, formule documentée
evaluation/client_llm.py      Groq, cache désactivable, versions journalisées
validation/harnais.py         métriques, IC de Wilson, seuils bloquants CI
validation/run_validation.py  CLI de validation et de non-régression
validation/test_garde_fous.py 22 tests de sûreté, sans appel API
securite/multi_tenant.py      RLS PostgreSQL + contexte obligatoire
securite/retention.py         durées de conservation, purge, droit à l'effacement
```

## Démarrage

```bash
# 1. Garde-fous, sans appel API ni quota
python -m validation.test_garde_fous

# 2. Chaîne complète en mode hors ligne (plancher de référence)
python -m validation.run_validation --corpus corpus_demo \
       --verite corpus_demo/verite_terrain.json --hors-ligne

# 3. Avec le vrai modèle, cache vidé entre exécutions
export GROQ_API_KEY=...
python -m validation.run_validation --corpus ./corpus \
       --verite ./verite_terrain.json --repetitions 3

# 4. En CI : code de sortie 1 si un seuil bloquant est violé
python -m validation.run_validation --corpus ./corpus \
       --verite ./verite_terrain.json --ci
```

Le client factice est un **plancher, pas une cible** : c'est une heuristique
lexicale naïve. Si Groq fait moins bien que lui, le problème vient du prompt.

## Câblage dans le backend

```python
from evaluation.client_llm import ClientGroq
from evaluation.evaluateur import Evaluateur
from securite.multi_tenant import contexte_tenant, ouvrir_session

evaluateur = Evaluateur(
    client=ClientGroq(),
    retriever=mon_retriever_pgvector,   # même signature (requete, passages, k)
)

@app.post("/audits")
async def creer_audit(fichier: UploadFile, tenant: str = Depends(tenant_depuis_jwt)):
    with contexte_tenant(tenant):
        ouvrir_session(connexion, tenant)
        rapport = evaluateur.evaluer_document(
            texte, nom=fichier.filename, tenant_id=tenant
        )
        return rapport.to_dict()
```

Le retriever par défaut est lexical, sans dépendance. Remplace-le par pgvector
en gardant la signature : le harnais compare alors les deux sur le même corpus,
ce qui te dit si ton retrieval sémantique apporte réellement quelque chose.

## Le point sur la reproductibilité

L'écart-type de 0,00 du run précédent doit être revérifié cache vidé. Un
déterminisme réel à température 0 est un argument solide ; un déterminisme de
cache est une faille qu'un jury trouvera. `ClientGroq(cache_actif=False)` est
imposé par le script de validation, et `--repetitions` vide le cache entre
chaque passe.

## Le corpus de validation

Cinq documents ne suffisent pas. Sur 66 articles à 89,4 %, l'intervalle de
confiance à 95 % est d'environ ±7 points : impossible de distinguer 89 % de 82 %.
Le harnais affiche désormais cet intervalle et prévient quand il est trop large.

Vise 15 à 20 documents, dont :

- 3 cas à dérogation applicable (santé 9(2)(h), RH 9(2)(b), collecte indirecte 14(5))
- 2 cas contradictoires : le document affirme une conformité que les détails démentent
- 2 cas de conformité partielle par article (registre existant mais incomplet)
- 2 cas hors périmètre strict (TPE sans DPO obligatoire, aucun transfert hors UE)
- 1 cas de document très long, pour éprouver le chunking

Le champ `jamais_exclure` de la vérité terrain liste les obligations réellement
dues : les écarter est suivi comme une faute distincte, parce qu'un outil
d'audit qui dit « ça ne vous concerne pas » à tort est bien pire qu'un outil
trop sévère.

## Attendu après refonte

Le rappel devrait passer de 76,9 % à 90 % et plus. Le score du doc 03 tombera de
80,7 vers 60-70, ce qui le ramène dans son intervalle. Attention : l'« écart
moyen de 0,1 point » du run précédent était flatté par le rappel faible — moins
de manquements détectés, scores plus hauts, intervalles larges qui absorbent
tout. Le harnais le signale désormais explicitement.

Si le rappel ne remonte pas, le problème est dans les `elements_attendus` du
référentiel, pas dans le modèle.

## Avant la mise en production

- [ ] `test_garde_fous` au vert en CI
- [ ] Seuils bloquants respectés sur un corpus d'au moins 15 documents
- [ ] Reproductibilité mesurée cache vidé, sur 3 exécutions
- [ ] RLS PostgreSQL appliquée, application connectée avec un rôle **non propriétaire**
- [ ] Index vectoriel filtré par tenant, filtre dans la requête et non après coup
- [ ] Test d'intégration prouvant qu'un tenant A ne voit aucune donnée d'un tenant B
- [ ] Purge programmée active et journalisée
- [ ] Mentions produit affichées (voir `MENTIONS.md`)
- [ ] Chaque verdict affiche sa citation source dans l'interface
- [ ] Versions du modèle et des embeddings figées dans chaque rapport
