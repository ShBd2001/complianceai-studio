"""
Référentiel d'audit AI Act — grille des éléments probants.

Même principe directeur que referentiel/articles.py (RGPD) : un verdict de
conformité ne peut être rendu que si CHAQUE élément probant bloquant est
couvert par une citation littérale du document audité. L'absence de preuve
vaut manquement.

Articles auditables (voir backend/app/ingestion/scoping.py::AI_ACT_AUDITABLE) :
5, 8-27, 47, 48, 49, 50, 72, 73, 86. Règlement (UE) 2024/1689, CELEX 32024R1689.

Quatre conditions d'applicabilité distinctes (voir DA-08,
backend/app/services/eligibilite.py) :
  - 5 : toujours applicable, jamais exempté ;
  - 8-21, 25, 47, 48, 72, 73 : fournisseur d'un système d'IA à haut risque ;
  - 22 : fournisseur établi hors de l'Union européenne (mandataire) ;
  - 23/24 : importateur ou distributeur d'un système d'IA (aucune régle
    d'éligibilité dédiée côté production — correction 5 — toujours évalué
    ici aussi) ;
  - 26 : déployeur d'un système d'IA à haut risque ;
  - 27/86 : sous-ensemble restreint des déployeurs (analyse d'impact,
    droit à l'explication) ;
  - 49 : fournisseur OU déployeur d'un système d'IA à haut risque ;
  - 50 : usage d'un système d'IA relevant des catégories visées par
    l'article (agents conversationnels, contenus de synthèse,
    reconnaissance des émotions, catégorisation biométrique).
"""

from __future__ import annotations

from referentiel.articles import ArticleRGPD, Criticite, _e

CONDITION_TOUJOURS = (
    "Cette disposition s'applique systématiquement, à toute organisation, "
    "qu'elle développe, déploie ou n'utilise aucun système d'intelligence "
    "artificielle. AUCUNE phrase du document, y compris une déclaration "
    "explicite d'absence de système d'IA ou de rôle de fournisseur/"
    "déployeur, ne permet d'écarter cette disposition du périmètre : "
    "réponds toujours \"applicable\": true, quelle que soit la citation "
    "trouvée ou son absence."
)
CONDITION_FOURNISSEUR = (
    "L'organisme développe, sous son propre nom ou sa propre marque, un "
    "système d'intelligence artificielle classé à haut risque au sens de "
    "l'annexe III du règlement (ou de l'annexe I), ET le met sur le marché "
    "OU le met en service — y compris pour son propre usage interne "
    "exclusif, sans jamais le commercialiser ni le distribuer à un tiers. "
    "La mise en service pour ses propres besoins suffit à constituer la "
    "qualité de fournisseur au sens du règlement : le fait qu'un système "
    "soit développé « en interne » ou « jamais commercialisé à des tiers » "
    "n'écarte PAS cette qualité, cela écarte seulement les obligations "
    "d'importateur ou de distributeur (articles 23/24), qui sont "
    "distinctes."
)
CONDITION_DEPLOYEUR = (
    "L'organisme utilise, sous sa propre autorité, un système "
    "d'intelligence artificielle à haut risque fourni par un tiers, dans "
    "le cadre de son activité professionnelle."
)
CONDITION_IMPORT_DISTRIB = (
    "L'organisme importe dans l'Union ou distribue un système "
    "d'intelligence artificielle développé par un tiers établi hors de "
    "l'Union, sans en être le fournisseur direct."
)
CONDITION_USAGE_IA = (
    "L'organisme utilise, fournit ou déploie un système d'intelligence "
    "artificielle destiné à interagir directement avec des personnes "
    "physiques (agent conversationnel), générant du contenu de synthèse "
    "ou de l'hypertrucage, procédant à de la reconnaissance des émotions, "
    "ou à de la catégorisation biométrique de personnes physiques."
)

REFERENTIEL_AI_ACT: tuple[ArticleRGPD, ...] = (
    ArticleRGPD(
        numero="5", intitule="Pratiques interdites en matière d'IA",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_TOUJOURS,
        elements_attendus=(
            _e("absence_pratiques_interdites",
               "Le document établit explicitement l'absence de pratiques interdites (notation sociale, manipulation subliminale, exploitation de vulnérabilités, catégorisation biométrique sensible, reconnaissance des émotions au travail, surveillance biométrique en temps réel non justifiée)",
               "aucune pratique interdite", "absence de notation sociale", "aucune technique subliminale"),
        ),
        note_auditeur=(
            "Article jamais exempté (voir la condition d'applicabilité ci-dessus, qui "
            "interdit explicitement toute exclusion). exclusion_exige_preuve reste à sa "
            "valeur par défaut (True) : la protection contre une exclusion à tort tient "
            "à la fois de l'instruction du prompt et de l'exigence de citation vérifiée, "
            "deux niveaux redondants, aucun n'étant infaillible seul face à un modèle réel. "
            "Un document muet sur ce point n'établit ni conformité ni manquement de façon "
            "certaine ; seule une description du système révélant une pratique interdite "
            "caractérisée doit conduire au manquement."
        ),
    ),
    ArticleRGPD(
        numero="8", intitule="Respect des exigences",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("dossier_conformite",
               "Un dossier de conformité documente le respect systématique des exigences du chapitre III, section 2, avant mise sur le marché",
               "dossier de conformité", "respect systématique"),
        ),
    ),
    ArticleRGPD(
        numero="9", intitule="Système de gestion des risques",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("systeme_gestion_risques",
               "Un système de gestion des risques est mis en œuvre tout au long du cycle de vie (identification, estimation, évaluation, atténuation)",
               "système de gestion des risques", "identification des risques", "mesures d'atténuation"),
        ),
    ),
    ArticleRGPD(
        numero="10", intitule="Données et gouvernance des données",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("gouvernance_donnees",
               "Les jeux de données d'entraînement, de validation et de test font l'objet d'un examen de pertinence, de représentativité et d'absence de biais",
               "gouvernance des données", "audit de biais", "représentativité"),
        ),
    ),
    ArticleRGPD(
        numero="11", intitule="Documentation technique",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("documentation_technique",
               "Une documentation technique complète, conforme à l'annexe IV, est établie et tenue à jour à chaque modification substantielle",
               "documentation technique", "annexe IV", "mise à jour"),
        ),
    ),
    ArticleRGPD(
        numero="12", intitule="Enregistrement",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("journalisation_automatique",
               "Le système génère automatiquement des journaux tout au long de son cycle de vie",
               "journaux générés automatiquement", "traçabilité"),
        ),
    ),
    ArticleRGPD(
        numero="13", intitule="Transparence et fourniture d'informations aux déployeurs",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("notice_utilisation",
               "Une notice d'utilisation précise les caractéristiques, limites et mesures de surveillance humaine attendues",
               "notice d'utilisation", "instructions", "limites de performance"),
        ),
    ),
    ArticleRGPD(
        numero="14", intitule="Contrôle humain",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("mesures_controle_humain",
               "Le système est conçu pour permettre une supervision humaine effective (validation, interruption, non-automaticité de la décision finale)",
               "contrôle humain", "supervision humaine", "validation par un opérateur", "fonction d'interruption"),
        ),
        note_auditeur=(
            "Vérifier la pratique effective, pas seulement la conception théorique : une "
            "politique qui prévoit une revue humaine mais dont les statistiques réelles "
            "montrent une automaticité quasi totale ne satisfait pas cet élément."
        ),
    ),
    ArticleRGPD(
        numero="15", intitule="Exactitude, robustesse et cybersécurité",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("metriques_exactitude",
               "Des métriques de précision et de robustesse sont mesurées et documentées",
               "métriques de précision", "robustesse", "tests de résistance"),
        ),
    ),
    ArticleRGPD(
        numero="16", intitule="Obligations incombant aux fournisseurs de systèmes d'IA à haut risque",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("pilotage_obligations",
               "L'ensemble des obligations de fournisseur (système qualité, documentation, enregistrement, marquage CE, coopération) est piloté de façon identifiable",
               "obligations du fournisseur", "pilotage qualité"),
        ),
        note_auditeur="Article de synthèse : ne pas double-compter avec les articles 17 à 21, qui détaillent chaque obligation séparément.",
    ),
    ArticleRGPD(
        numero="17", intitule="Système de gestion de la qualité",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("systeme_qualite",
               "Un système de gestion de la qualité couvrant conception, développement, contrôle qualité et surveillance post-commercialisation est en place",
               "système de gestion de la qualité", "SGQ"),
        ),
    ),
    ArticleRGPD(
        numero="18", intitule="Conservation des documents",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("duree_conservation",
               "La documentation technique et les journaux sont conservés pendant la durée requise (dix ans après mise sur le marché)",
               "conservation", "dix ans"),
        ),
    ),
    ArticleRGPD(
        numero="19", intitule="Journaux générés automatiquement",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("conservation_journaux",
               "Les journaux générés par le système sont conservés pendant une durée appropriée à sa finalité",
               "conservation des journaux", "durée appropriée"),
        ),
    ),
    ArticleRGPD(
        numero="20", intitule="Mesures correctives et devoir d'information",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("procedure_corrective",
               "Une procédure de retrait, désactivation ou rappel du système et d'information des autorités et déployeurs est prévue",
               "mesures correctives", "retrait", "rappel", "information des autorités"),
        ),
    ),
    ArticleRGPD(
        numero="21", intitule="Coopération avec les autorités compétentes",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("contact_designe",
               "Un contact désigné répond aux demandes des autorités de surveillance dans les délais",
               "contact désigné", "coopération avec les autorités"),
        ),
    ),
    ArticleRGPD(
        numero="22", intitule="Mandataires des fournisseurs de systèmes d'IA à haut risque",
        criticite=Criticite.MODEREE,
        condition_applicabilite=(
            "L'organisme fournisseur d'un système d'IA à haut risque est "
            "établi en dehors de l'Union européenne."
        ),
        elements_attendus=(
            _e("mandataire_designe",
               "Un mandataire établi dans l'Union européenne est désigné par mandat écrit",
               "mandataire", "mandat écrit"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="23", intitule="Obligations des importateurs",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_IMPORT_DISTRIB,
        elements_attendus=(
            _e("verifications_importateur",
               "L'importateur vérifie la conformité du système avant mise sur le marché (déclaration UE, documentation, marquage CE)",
               "importateur", "vérification avant mise sur le marché"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="24", intitule="Obligations des distributeurs",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_IMPORT_DISTRIB,
        elements_attendus=(
            _e("verifications_distributeur",
               "Le distributeur vérifie la présence du marquage CE, de la déclaration de conformité et de la documentation avant mise à disposition",
               "distributeur", "vérification"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="25", intitule="Responsabilités tout au long de la chaîne de valeur de l'IA",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("clarification_responsabilites",
               "Les contrats précisent le transfert des obligations de fournisseur en cas de modification substantielle par un tiers",
               "chaîne de valeur", "transfert des obligations", "modification substantielle"),
        ),
    ),
    ArticleRGPD(
        numero="26", intitule="Obligations incombant aux déployeurs de systèmes d'IA à haut risque",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=CONDITION_DEPLOYEUR,
        elements_attendus=(
            _e("controle_humain_deployeur",
               "Le déployeur assure un contrôle humain effectif et une surveillance du fonctionnement du système",
               "contrôle humain", "surveillance du système", "formation des utilisateurs"),
            _e("information_personnes",
               "Les personnes affectées par une décision fondée sur le système sont informées de son utilisation",
               "information des personnes concernées", "décision automatisée"),
        ),
    ),
    ArticleRGPD(
        numero="27", intitule="Analyse d'impact des systèmes d'IA à haut risque sur les droits fondamentaux",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=(
            "L'organisme est déployeur d'un système d'IA à haut risque "
            "relevant des catégories visées à l'article 27 (notamment "
            "services publics essentiels, évaluation de solvabilité, "
            "assurance vie et santé, ou déployeur de droit public)."
        ),
        elements_attendus=(
            _e("analyse_impact_realisee",
               "Une analyse d'impact sur les droits fondamentaux a été réalisée avant la mise en service et renouvelée après toute modification substantielle",
               "analyse d'impact", "droits fondamentaux"),
        ),
    ),
    ArticleRGPD(
        numero="47", intitule="Déclaration UE de conformité",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("declaration_conformite",
               "Une déclaration UE de conformité est établie et signée pour chaque version majeure du système",
               "déclaration UE de conformité", "signée"),
        ),
    ),
    ArticleRGPD(
        numero="48", intitule="Marquage CE",
        criticite=Criticite.MINEURE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("marquage_ce",
               "Le marquage CE est apposé conformément aux exigences applicables",
               "marquage CE", "apposé"),
        ),
    ),
    ArticleRGPD(
        numero="49", intitule="Enregistrement",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=(
            "L'organisme est fournisseur d'un système d'IA à haut risque, "
            "ou déployeur d'un système d'IA à haut risque relevant des "
            "catégories de déployeurs soumises à enregistrement (notamment "
            "les organismes publics)."
        ),
        elements_attendus=(
            _e("enregistrement_base_ue",
               "Le système, ou son utilisation par le déployeur, est enregistré dans la base de données de l'Union européenne, mis à jour à chaque modification substantielle",
               "base de données de l'Union", "enregistré", "enregistrement"),
        ),
    ),
    ArticleRGPD(
        numero="50", intitule="Obligations de transparence pour les fournisseurs et les déployeurs de certains systèmes d'IA",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_USAGE_IA,
        elements_attendus=(
            _e("information_interaction_ia",
               "Les personnes sont informées qu'elles interagissent avec un système d'IA, ou qu'un contenu est généré ou manipulé artificiellement",
               "assistant automatisé", "contenu généré par IA", "hypertrucage", "divulgation"),
        ),
        exclusion_exige_preuve=True,
    ),
    ArticleRGPD(
        numero="72", intitule="Surveillance après commercialisation par les fournisseurs et plan de surveillance après commercialisation pour les systèmes d'IA à haut risque",
        criticite=Criticite.MODEREE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("plan_surveillance",
               "Un plan de surveillance post-commercialisation collecte et analyse les retours d'utilisation et incidents",
               "surveillance après commercialisation", "retours d'utilisation"),
        ),
    ),
    ArticleRGPD(
        numero="73", intitule="Signalement d'incidents graves",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite=CONDITION_FOURNISSEUR,
        elements_attendus=(
            _e("procedure_signalement",
               "Une procédure de signalement des incidents graves aux autorités compétentes, avec délais alignés sur la gravité, est formalisée",
               "signalement d'incidents graves", "délai"),
        ),
    ),
    ArticleRGPD(
        numero="86", intitule="Droit à l'explication des décisions individuelles",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=(
            "L'organisme est déployeur d'un système d'IA à haut risque qui "
            "produit des effets juridiques ou affecte de manière "
            "significative une personne physique dans un contexte "
            "relevant de l'article 86 (ex. évaluation de solvabilité)."
        ),
        elements_attendus=(
            _e("explication_fournie",
               "Une explication claire et significative des éléments ayant conduit à une décision est fournie à la personne concernée qui en fait la demande, sans retard indu",
               "droit à l'explication", "explication individuelle", "sans retard indu"),
        ),
    ),
)
