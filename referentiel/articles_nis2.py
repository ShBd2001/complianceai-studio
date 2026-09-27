"""
Référentiel d'audit NIS2 — grille des éléments probants.

Même principe directeur que referentiel/articles.py (RGPD) : un verdict de
conformité ne peut être rendu que si CHAQUE élément probant bloquant est
couvert par une citation littérale du document audité. L'absence de preuve
vaut manquement.

Articles auditables (voir backend/app/ingestion/scoping.py::NIS2_AUDITABLE) :
20, 21, 23, 24, 27, 28, 29, 30. Directive (UE) 2022/2555, CELEX 32022L2555.

Deux conditions d'applicabilité distinctes (voir DA-08,
backend/app/services/eligibilite.py, correction 1) :
  - 20/21/23/24/29/30 : statut général d'entité essentielle ou importante ;
  - 27/28 : fourniture d'un service DNS ou d'un registre/bureau
    d'enregistrement de noms de domaine — périmètre plus étroit, une entité
    essentielle/importante « générique » n'y répond pas forcément.
"""

from __future__ import annotations

from referentiel.articles import ArticleRGPD, Criticite, _e

CONDITION_STATUT_GENERAL = (
    "L'organisme est désigné, ou se déclare lui-même, comme entité "
    "essentielle ou importante au sens de la directive NIS2 (secteur visé "
    "aux annexes I ou II, seuils d'effectif ou de chiffre d'affaires "
    "dépassés)."
)
CONDITION_DNS = (
    "L'organisme exploite un service DNS pour des tiers, un registre de "
    "noms de domaine de premier niveau, ou un bureau d'enregistrement de "
    "noms de domaine."
)

REFERENTIEL_NIS2: tuple[ArticleRGPD, ...] = (
    ArticleRGPD(
        numero="20",
        intitule="Gouvernance",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_STATUT_GENERAL,
        elements_attendus=(
            _e("approbation_organe_direction",
               "Les mesures de gestion des risques en matière de cybersécurité sont approuvées par l'organe de direction",
               "approuve", "conseil de direction", "conseil d'administration"),
            _e("formation_dirigeants",
               "Les membres de l'organe de direction suivent une formation ou une sensibilisation à la cybersécurité",
               "formation", "sensibilisation", "membres du conseil"),
            _e("responsable_designe",
               "Un responsable de la sécurité des systèmes d'information est désigné et rattaché à la direction",
               "responsable de la sécurité", "DSIS", "RSSI", "rattaché"),
        ),
        note_auditeur=(
            "L'article 20 vise la gouvernance au niveau de l'organe de direction lui-même "
            "(responsabilité personnelle en cas de manquement), pas seulement l'existence "
            "d'une fonction sécurité opérationnelle."
        ),
    ),
    ArticleRGPD(
        numero="21",
        intitule="Mesures de gestion des risques en matière de cybersécurité",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_STATUT_GENERAL,
        elements_attendus=(
            _e("analyse_risques",
               "Politique d'analyse des risques et de sécurité des systèmes d'information, documentée et mise à jour",
               "analyse de risques", "politique de sécurité", "cartographie des risques"),
            _e("gestion_incidents",
               "Procédure de gestion des incidents (détection, qualification, escalade)",
               "gestion des incidents", "procédure d'incident", "astreinte"),
            _e("continuite_reprise",
               "Plan de continuité d'activité et plan de reprise après sinistre, testés",
               "plan de continuité", "reprise après sinistre", "exercice de crise", "sauvegarde"),
            _e("chaine_approvisionnement",
               "Politique de sécurité de la chaîne d'approvisionnement (clauses de sécurité dans les contrats fournisseurs)",
               "chaîne d'approvisionnement", "clause de sécurité", "contrat fournisseur", "prestataire"),
            _e("hygiene_authentification",
               "Pratiques d'hygiène informatique de base et authentification multifacteurs sur les accès sensibles",
               "authentification multifacteurs", "hygiène informatique", "gestion des correctifs", "mots de passe"),
            _e("evaluation_efficacite",
               "Évaluation périodique de l'efficacité des mesures de gestion des risques (audit interne ou externe)",
               "audit interne", "audit externe", "évaluation de l'efficacité",
               bloquant=False),
        ),
        note_auditeur=(
            "L'article 21§2 (a à j) couvre dix catégories de mesures. Les six éléments "
            "ci-dessus en sont un sous-ensemble représentatif ; l'absence de preuve sur "
            "plusieurs d'entre eux, même non bloquants, doit être signalée en recommandation."
        ),
    ),
    ArticleRGPD(
        numero="23",
        intitule="Obligations d'information",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_STATUT_GENERAL,
        elements_attendus=(
            _e("procedure_notification",
               "Procédure formalisée de notification des incidents importants au CSIRT national ou à l'autorité compétente",
               "notification d'incident", "CSIRT", "autorité compétente"),
            _e("delai_alerte_precoce",
               "L'alerte précoce est prévue sous 24 heures après la détection d'un incident important",
               "alerte précoce", "24 heures"),
            _e("delai_rapport_final",
               "Un rapport final est prévu, au plus tard un mois après l'incident",
               "rapport final", "un mois"),
        ),
    ),
    ArticleRGPD(
        numero="24",
        intitule="Recours aux schémas européens de certification de cybersécurité",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_STATUT_GENERAL,
        elements_attendus=(
            _e("exigence_certification",
               "Les achats ou le développement de produits, services ou processus TIC tiennent compte de schémas européens de certification de cybersécurité lorsqu'ils existent",
               "certification européenne", "schéma de certification", "certifié"),
        ),
        note_auditeur=(
            "Le recours à des schémas de certification n'est une obligation ferme de "
            "l'entité que si un acte délégué de la Commission ou le droit national l'impose "
            "pour la catégorie de produit concernée ; en l'absence d'une telle obligation "
            "précisée dans le document, une pratique volontaire documentée suffit à "
            "retenir la conformité, faute de quoi le silence du document ne doit pas être "
            "sur-interprété comme un manquement certain."
        ),
    ),
    ArticleRGPD(
        numero="27",
        intitule="Registre des entités",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_DNS,
        elements_attendus=(
            _e("enregistrement_registre",
               "L'organisme est enregistré auprès de l'autorité compétente ou de l'ENISA en tant que registre de noms de domaine de premier niveau",
               "registre des entités", "enregistré auprès de", "ENISA"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="28",
        intitule="Base des données d'enregistrement des noms de domaine",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_DNS,
        elements_attendus=(
            _e("donnees_enregistrement_exactes",
               "Une base de données précise et complète des données d'enregistrement de noms de domaine est tenue",
               "données d'enregistrement", "base de données", "titulaire du nom de domaine"),
            _e("procedure_verification",
               "Une procédure de vérification des données d'enregistrement est décrite",
               "vérification des données", "procédure de vérification"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="29",
        intitule="Accords de partage d'informations en matière de cybersécurité",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_STATUT_GENERAL,
        elements_attendus=(
            _e("participation_partage",
               "Participation active et documentée à un dispositif de partage d'informations sur les cybermenaces (secteur, ISAC, autorité)",
               "partage d'informations", "dispositif sectoriel", "indicateurs de compromission"),
        ),
        note_auditeur=(
            "Disposition volontaire par nature (art. 29§1 : « peuvent participer »). Une "
            "simple adhésion sans mise en œuvre documentée (aucun échange réel constaté) "
            "ne doit toutefois pas être retenue comme satisfaisant l'élément : l'audit "
            "porte sur la pratique effective, pas sur la seule appartenance formelle."
        ),
    ),
    ArticleRGPD(
        numero="30",
        intitule="Notification volontaire d'informations pertinentes",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_STATUT_GENERAL,
        elements_attendus=(
            _e("notifications_volontaires",
               "Des notifications volontaires (incidents mineurs, cybermenaces, quasi-incidents) ont été transmises au CSIRT national",
               "notification volontaire", "cybermenace", "quasi-incident", "tentative d'intrusion"),
        ),
        note_auditeur="Disposition volontaire (art. 30§1 : « peuvent notifier »), mais l'audit vérifie la pratique effective, pas seulement son principe.",
    ),
)
