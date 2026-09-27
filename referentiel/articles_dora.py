"""
Référentiel d'audit DORA — grille des éléments probants.

Même principe directeur que referentiel/articles.py (RGPD) : un verdict de
conformité ne peut être rendu que si CHAQUE élément probant bloquant est
couvert par une citation littérale du document audité. L'absence de preuve
vaut manquement.

Articles auditables côté PRODUCTION (voir backend/app/ingestion/scoping.py::
DORA_AUDITABLE) : 5 à 30. Règlement (UE) 2022/2554, CELEX 32022R2554.

Écart assumé avec la PRODUCTION : les articles 15, 20 et 21 sont des
obligations purement institutionnelles entre autorités européennes de
surveillance (EBA/ESMA/EIOPA), jamais une obligation de l'entité financière
elle-même — en production, le filtre d'éligibilité (backend/app/services/
eligibilite.py::_dora_institutionnel) les exempte inconditionnellement,
sans dépendre du contenu du document. Le laboratoire, lui, ne dispose
d'aucun mécanisme d'exemption indépendant du contenu : sa décision
d'applicabilité repose sur une citation extraite du document, et sa propre
consigne de prompt fait défaut à "applicable" en l'absence de citation
(aucun document d'entreprise ne cite jamais les obligations propres des
autorités de surveillance entre elles). Les inclure produirait donc de
faux manquements systématiques plutôt qu'une exemption correcte. Ces trois
articles sont volontairement ABSENTS de cette grille plutôt que mal
modélisés — écart documenté, pas un oubli.
"""

from __future__ import annotations

from referentiel.articles import ArticleRGPD, Criticite, _e

CONDITION_ENTITE_FINANCIERE = (
    "L'organisme est une entité financière au sens de l'article 2 du "
    "règlement DORA (établissement de crédit, établissement de paiement, "
    "établissement de monnaie électronique, entreprise d'investissement, "
    "prestataire de services sur crypto-actifs, entreprise d'assurance ou "
    "de réassurance, société de gestion, etc.)."
)
CONDITION_PAIEMENT = (
    "L'organisme est un établissement de crédit, un établissement de "
    "paiement, un établissement de monnaie électronique, ou un "
    "prestataire de services d'information sur les comptes."
)

REFERENTIEL_DORA: tuple[ArticleRGPD, ...] = (
    ArticleRGPD(
        numero="5", intitule="Gouvernance et organisation",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("responsabilite_organe_direction",
               "L'organe de direction assume et approuve le cadre de gestion du risque lié aux TIC",
               "conseil d'administration", "approuve", "responsabilité"),
            _e("responsable_designe",
               "Un responsable des risques TIC ou une fonction équivalente est désigné, rattaché à la direction générale",
               "responsable des risques TIC", "comité des risques", "rattaché"),
        ),
    ),
    ArticleRGPD(
        numero="6", intitule="Cadre de gestion du risque lié aux TIC",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("cadre_documente",
               "Un cadre de gestion du risque lié aux TIC est documenté et couvre stratégie, politiques et procédures",
               "cadre de gestion du risque", "stratégie de résilience", "politique de sécurité de l'information"),
            _e("revue_periodique",
               "Le cadre est revu périodiquement et après tout incident majeur",
               "revu chaque année", "audit interne", "mise à jour"),
        ),
    ),
    ArticleRGPD(
        numero="7", intitule="Systèmes, protocoles et outils de TIC",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("inventaire_systemes",
               "Les systèmes, protocoles et outils TIC sont inventoriés et maintenus à jour",
               "inventaire", "composants critiques", "plan de remplacement"),
        ),
    ),
    ArticleRGPD(
        numero="8", intitule="Identification",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("cartographie_actifs",
               "Une cartographie des actifs informationnels et des fonctions critiques ou importantes est tenue à jour",
               "cartographie des actifs", "fonctions critiques", "dépendances"),
        ),
    ),
    ArticleRGPD(
        numero="9", intitule="Protection et prévention",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("chiffrement",
               "Chiffrement des données au repos et en transit",
               "chiffrement", "chiffrées"),
            _e("gestion_acces",
               "Gestion des accès selon le principe du moindre privilège, avec authentification multifacteurs",
               "moindre privilège", "authentification multifacteurs", "habilitations"),
        ),
    ),
    ArticleRGPD(
        numero="10", intitule="Détection",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("dispositif_detection",
               "Un dispositif de détection des anomalies et des incidents est en place (SOC, supervision continue)",
               "détection des anomalies", "supervision", "SOC", "surveillance continue"),
        ),
    ),
    ArticleRGPD(
        numero="11", intitule="Réponse et rétablissement",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("plan_reponse_incidents",
               "Un plan de réponse aux incidents liés aux TIC est formalisé",
               "plan de réponse aux incidents", "procédure d'incident"),
            _e("plan_continuite",
               "Un plan de continuité d'activité couvrant les fonctions critiques est formalisé et testé",
               "plan de continuité d'activité", "exercice de crise", "testé"),
        ),
    ),
    ArticleRGPD(
        numero="12", intitule="Politiques et procédures de sauvegarde, procédures et méthodes de restauration et de rétablissement",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("politique_sauvegarde",
               "Une politique de sauvegarde documentée est appliquée, avec sauvegardes régulières",
               "politique de sauvegarde", "sauvegardes quotidiennes", "chiffrées"),
            _e("test_restauration",
               "Des tests de restauration sont réalisés périodiquement",
               "test de restauration", "compte-rendu"),
        ),
    ),
    ArticleRGPD(
        numero="13", intitule="Apprentissage et évolution",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("retour_experience",
               "Un retour d'expérience formalisé est réalisé après chaque incident significatif",
               "retour d'expérience", "registre des enseignements"),
            _e("sensibilisation",
               "Des sessions de sensibilisation ou de formation du personnel aux risques TIC sont organisées",
               "sensibilisation", "formation", "campagne"),
        ),
    ),
    ArticleRGPD(
        numero="14", intitule="Communication",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("plan_communication_crise",
               "Un plan de communication de crise définit les messages et destinataires en cas d'incident majeur",
               "plan de communication de crise", "communication de crise"),
        ),
    ),
    ArticleRGPD(
        numero="16", intitule="Cadre simplifié de gestion du risque lié aux TIC",
        criticite=Criticite.MINEURE,
        condition_applicabilite=(
            "L'organisme relève de l'une des catégories éligibles au cadre "
            "simplifié de gestion du risque lié aux TIC (notamment les "
            "petites entreprises d'investissement non interconnectées et "
            "catégories assimilées de l'article 16§1)."
        ),
        elements_attendus=(
            _e("cadre_simplifie_applique",
               "Le cadre simplifié applicable est documenté et appliqué en lieu et place du cadre complet",
               "cadre simplifié", "éligible"),
        ),
        note_auditeur=(
            "Article ambigu à trancher au cas par cas : une entité qui applique le cadre "
            "COMPLET (articles 5 à 15) sans revendiquer le cadre simplifié n'est pas en "
            "manquement de l'article 16, elle choisit simplement le régime le plus "
            "protecteur. Ne conclure au manquement que si l'organisme revendique "
            "explicitement son éligibilité au cadre simplifié sans en appliquer le contenu."
        ),
    ),
    ArticleRGPD(
        numero="17", intitule="Processus de gestion des incidents liés aux TIC",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("processus_gestion_incidents",
               "Un processus de gestion des incidents TIC est documenté (détection, journalisation, qualification, escalade)",
               "processus de gestion des incidents", "qualification", "escalade"),
        ),
    ),
    ArticleRGPD(
        numero="18", intitule="Classification des incidents liés aux TIC et des cybermenaces",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("criteres_classification",
               "Des critères de classification de la gravité des incidents sont documentés",
               "critères de classification", "gravité", "criticité des services"),
        ),
    ),
    ArticleRGPD(
        numero="19", intitule="Déclaration des incidents majeurs liés aux TIC et notification volontaire des cybermenaces importantes",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("procedure_declaration",
               "Une procédure de notification des incidents majeurs à l'autorité de contrôle est formalisée",
               "notification à l'autorité", "notification initiale", "rapport final"),
            _e("respect_delais",
               "Les délais de notification (initiale, intermédiaire, finale) sont effectivement respectés en pratique",
               "délai", "transmis dans les délais", "sous 24 heures"),
        ),
    ),
    ArticleRGPD(
        numero="22", intitule="Retour d'information en matière de surveillance",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("prise_en_compte_retour",
               "Le retour d'information transmis par l'autorité de contrôle est examiné et donne lieu à des actions correctives",
               "retour de l'autorité", "actions correctives", "comité des risques"),
        ),
    ),
    ArticleRGPD(
        numero="23",
        intitule="Incidents opérationnels ou de sécurité liés au paiement",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_PAIEMENT,
        elements_attendus=(
            _e("regime_specifique_paiement",
               "Un régime de déclaration spécifique aux incidents liés au paiement est appliqué, distinct du régime général des incidents TIC",
               "incidents liés au paiement", "moyens de paiement", "régime spécifique"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="24", intitule="Exigences générales applicables à la réalisation de tests de résilience opérationnelle numérique",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("programme_tests",
               "Un programme de tests de résilience opérationnelle numérique, proportionné au profil de risque, est documenté",
               "programme de tests", "résilience opérationnelle numérique"),
        ),
    ),
    ArticleRGPD(
        numero="25", intitule="Test des outils et systèmes de TIC",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("tests_vulnerabilite",
               "Des tests de vulnérabilité réguliers sont réalisés sur les systèmes",
               "test de vulnérabilité", "analyse de la sécurité des réseaux"),
        ),
    ),
    ArticleRGPD(
        numero="26", intitule="Tests avancés d'outils, de systèmes et de processus de TIC sur la base de tests de pénétration fondés sur la menace",
        criticite=Criticite.MODEREE,
        condition_applicabilite=(
            "L'organisme est une entité financière dont le profil de risque, "
            "l'importance systémique ou la taille justifient la réalisation "
            "de tests de pénétration fondés sur la menace (TLPT), ou "
            "l'organisme affirme explicitement en réaliser."
        ),
        elements_attendus=(
            _e("tlpt_realise",
               "Un test de pénétration fondé sur la menace (TLPT) est réalisé périodiquement, avec des testeurs accrédités",
               "test de pénétration fondé sur la menace", "TLPT", "TIBER-EU"),
        ),
        note_auditeur=(
            "Obligation proportionnée par nature : ne pas conclure au manquement pour une "
            "petite structure dont rien n'indique qu'elle relève du périmètre TLPT."
        ),
    ),
    ArticleRGPD(
        numero="27", intitule="Exigences applicables aux testeurs afin de réaliser des tests de pénétration fondés sur la menace",
        criticite=Criticite.MINEURE,
        condition_applicabilite=(
            "L'organisme réalise ou fait réaliser des tests de pénétration "
            "fondés sur la menace (TLPT)."
        ),
        elements_attendus=(
            _e("testeurs_accredites",
               "Les testeurs internes ou externes mobilisés disposent des accréditations et garanties requises",
               "testeurs accrédités", "assurance responsabilité civile"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="28", intitule="Principes généraux",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("strategie_risque_tiers",
               "Une stratégie relative au risque lié aux prestataires tiers de TIC est formalisée",
               "stratégie relative au risque", "prestataires tiers"),
            _e("registre_contrats",
               "Un registre des accords contractuels avec les prestataires TIC est tenu à jour",
               "registre des contrats", "accords contractuels"),
        ),
    ),
    ArticleRGPD(
        numero="29", intitule="Évaluation préliminaire du risque de concentration de TIC au niveau de l'entité",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("evaluation_concentration",
               "Une évaluation du risque de concentration lié au recours à un nombre restreint de prestataires TIC critiques est réalisée",
               "risque de concentration", "prestataires critiques"),
        ),
    ),
    ArticleRGPD(
        numero="30", intitule="Principales dispositions contractuelles",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_ENTITE_FINANCIERE,
        elements_attendus=(
            _e("clauses_essentielles",
               "Les contrats avec les prestataires TIC comportent une description des services, des clauses d'audit et une stratégie de sortie",
               "clause d'audit", "stratégie de sortie", "réversibilité"),
            _e("localisation_donnees",
               "Les conditions de localisation et de protection des données sont précisées dans les contrats",
               "localisation des données", "protection des données"),
        ),
    ),
)
