"""
Prompts de la chaîne d'évaluation.

Le modèle n'est jamais chargé de rendre un verdict. Il extrait des faits :
l'article s'applique-t-il, telle phrase du document couvre-t-elle tel élément
attendu, telle dérogation trouve-t-elle appui dans le texte. Le verdict est
calculé par le code à partir de ces faits.

Cette séparation est ce qui rend le système auditable : chaque conclusion
remonte à une citation vérifiable, pas à une appréciation.
"""

from __future__ import annotations

from referentiel.articles import ArticleRGPD

SYSTEME = (
    "Tu es un assistant d'extraction factuelle au service d'un audit RGPD. "
    "Tu ne donnes jamais d'avis, tu ne juges pas, tu n'infères rien. "
    "Tu recopies littéralement des extraits du document fourni et tu indiques "
    "s'ils couvrent un point précis. "
    "Toute citation que tu produis doit être copiée MOT POUR MOT depuis le "
    "document. Inventer, reformuler, résumer ou compléter une citation est une "
    "faute grave : les citations sont vérifiées automatiquement contre le texte "
    "source et une citation introuvable invalide ta réponse. "
    "Si un point n'est pas couvert, dis-le : c'est une réponse correcte et utile. "
    "Tu réponds exclusivement par un objet JSON valide, sans texte avant ni après, "
    "sans balises Markdown."
)


def prompt_applicabilite(art: ArticleRGPD, extraits: str) -> str:
    return f"""Tu examines si l'article {art.numero} du RGPD ({art.intitule}) concerne l'organisme décrit.

CONDITION D'APPLICABILITÉ DE L'ARTICLE :
{art.condition_applicabilite}

Si cette condition relie plusieurs branches par "OU" (ou "au moins une des
N conditions"), chaque branche est indépendante et suffisante à elle seule :
l'article est applicable dès qu'UNE branche est remplie, même si une autre ne
l'est pas. Écarter une branche (ex. un effectif réduit) ne dispense jamais
d'examiner les autres (ex. le traitement est-il occasionnel ? comporte-t-il
un risque pour les droits et libertés ?) — ne conclus jamais "non applicable"
sur la seule base d'une branche écartée quand la condition en comporte
plusieurs.

EXTRAITS DU DOCUMENT :
\"\"\"
{extraits}
\"\"\"

Procède en deux temps, sans sauter d'étape.

ÉTAPE 1 — Recherche factuelle, branche par branche s'il y en a plusieurs.
Le document contient-il une phrase qui renseigne sur au moins une des
branches de la condition ci-dessus ? Elle peut aller dans un sens comme dans
l'autre. Exemples de phrases renseignantes : un effectif chiffré, la
localisation des destinataires, la nature de l'activité, le caractère
occasionnel ou régulier du traitement, la présence ou l'absence d'une revue
humaine, le type de données traitées. Recopie la phrase la plus déterminante
mot pour mot dans "citation", ou mets null si le document ne dit rien sur
aucune branche.

ÉTAPE 2 — Conclusion, à partir de l'étape 1 uniquement.
- Condition à une seule branche : la citation montre qu'elle EST remplie →
  "applicable": true ; qu'elle N'EST PAS remplie → "applicable": false.
- Condition à plusieurs branches ("OU") : "applicable": true dès qu'une
  branche est remplie, OU que le document ne prouve pas que TOUTES les
  branches sont écartées. "applicable": false seulement si le document
  démontre explicitement qu'aucune branche ne s'applique.
- Si "citation" est null → "applicable": true

Cette dernière règle est importante : un document muet sur un sujet ne prouve
rien, et une obligation légale ne disparaît pas parce qu'elle n'est pas
mentionnée. Mais lorsque le document renseigne clairement une condition à une
seule branche dans le sens négatif, conclure "false" est la bonne réponse, et
non une prise de risque.

Réponds uniquement par ce JSON :
{{
  "citation": "phrase littérale renseignant une branche de la condition, ou null",
  "condition_remplie": true,
  "applicable": true,
  "justification": "une phrase, qui mentionne chaque branche examinée si la condition en comporte plusieurs"
}}"""


def prompt_extraction(art: ArticleRGPD, extraits: str, contexte_reglementaire: str) -> str:
    elements = "\n".join(
        f'  - cle="{e.cle}" : {e.intitule}' for e in art.elements_attendus
    )
    note = f"\nPOINT DE VIGILANCE :\n{art.note_auditeur}\n" if art.note_auditeur else ""
    reglementaire = (
        f"\nRÉFÉRENCE RÉGLEMENTAIRE :\n{contexte_reglementaire}\n"
        if contexte_reglementaire
        else ""
    )

    return f"""Article {art.numero} du RGPD — {art.intitule}.
{reglementaire}
Pour CHACUN des éléments ci-dessous, cherche dans le document une phrase qui le couvre explicitement.

ÉLÉMENTS À RECHERCHER :
{elements}
{note}
DOCUMENT AUDITÉ :
\"\"\"
{extraits}
\"\"\"

Règles impératives :
1. "satisfait": true exige une citation LITTÉRALE du document couvrant explicitement l'élément. Copie-colle, ne reformule pas.
1bis. Une MÊME phrase peut couvrir PLUSIEURS éléments. C'est fréquent : une notice
   d'information énumère souvent en une phrase les finalités, les destinataires et
   les durées. Recopie alors cette phrase pour CHACUN des éléments qu'elle couvre.
   Ne te retiens pas de la répéter : ce n'est pas une redondance, c'est la réponse
   attendue. Laisser un élément à null au motif que la phrase a déjà servi est une
   erreur, et elle conduit à signaler un manquement qui n'existe pas.
1ter. À l'inverse, un élément peut être couvert par PLUSIEURS phrases éloignées dans
   le document. Utilise alors le champ "citations" (au pluriel) pour en fournir la
   liste. Chaque entrée doit être une citation littérale distincte.
2. Une affirmation générale ("nous respectons le RGPD", "nous sommes vigilants sur la sécurité") ne satisfait aucun élément précis.
3. Ne déduis JAMAIS un élément d'un autre. Une bonne maturité sur un sujet ne prouve rien sur un sujet voisin. Si le document décrit une politique de sécurité robuste, cela ne prouve ni l'existence d'un registre, ni celle d'une procédure de notification.
4. L'absence d'une mention est une information valide et attendue : réponds "satisfait": false, "citation": null.
5. Renvoie exactement un objet par élément, avec la même valeur de "cle".

Réponds uniquement par ce JSON :
{{
  "elements": [
    {{
      "cle": "identifiant de l'élément",
      "satisfait": false,
      "citation": null,
      "citations": [],
      "commentaire": "ce qui est présent ou ce qui manque, en une phrase"
    }}
  ]
}}"""


def prompt_derogation(art: ArticleRGPD, extraits: str, manquants: list[str]) -> str:
    liste = "\n".join(
        f'  - reference="{d.reference}" ({d.intitule}) : {d.condition}'
        for d in art.derogations_ex_ante
    )
    return f"""Un manquement à l'article {art.numero} du RGPD ({art.intitule}) est envisagé, faute de preuve pour : {", ".join(manquants)}.

Avant de conclure, vérifie si une dérogation légale s'applique à l'organisme décrit.

DÉROGATIONS POSSIBLES :
{liste}

DOCUMENT AUDITÉ :
\"\"\"
{extraits}
\"\"\"

Règles :
- Retiens une dérogation uniquement si le document décrit une situation qui correspond à sa condition.
- La citation doit être copiée mot pour mot depuis le document.
- Si aucune dérogation ne s'applique, réponds "reference": null. C'est le cas le plus fréquent.

Réponds uniquement par ce JSON :
{{
  "reference": null,
  "citation": null,
  "justification": "pourquoi cette dérogation s'applique, ou pourquoi aucune ne s'applique"
}}"""
