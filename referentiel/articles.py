"""
Référentiel d'audit RGPD — grille des éléments probants.

Principe directeur : un verdict de conformité ne peut être rendu que si CHAQUE
élément probant attendu est couvert par une citation littérale du document
audité. L'absence de preuve vaut manquement. Le modèle n'émet pas d'avis,
il extrait des preuves ; c'est le code qui rend le verdict.

Les `indices` ne sont PAS des déclencheurs de conformité : ils servent
uniquement à orienter le retrieval. Trouver le mot "registre" dans un document
ne prouve rien.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Criticite(int, Enum):
    """Poids d'un article dans le score global de conformité."""

    MINEURE = 1
    MODEREE = 2
    IMPORTANTE = 3
    MAJEURE = 4
    CRITIQUE = 5


@dataclass(frozen=True)
class ElementProbant:
    """Un élément que le document doit démontrer pour que l'article soit conforme."""

    cle: str
    intitule: str
    indices: tuple[str, ...] = ()
    # Un élément non bloquant n'empêche pas la conformité s'il est absent,
    # mais dégrade la confiance et remonte en recommandation.
    bloquant: bool = True


@dataclass(frozen=True)
class Derogation:
    """Exception légale susceptible d'écarter un manquement présumé."""

    reference: str
    intitule: str
    condition: str
    # Certaines dérogations ne s'apprécient que face à un incident concret
    # (art. 34(3) : telle violation précise, telles données précises). Les
    # proposer lors d'un audit documentaire conduit le modèle à les retenir
    # à tort comme une exemption générale. Elles sont exclues de la passe.
    evaluable_ex_ante: bool = True
    # Deux natures très différentes de dérogation :
    #  - "hors_perimetre" : l'obligation ne s'applique pas (art. 14(5)).
    #  - "conforme" : l'obligation s'applique et se trouve SATISFAITE par la
    #    dérogation. C'est le cas de l'article 9(2) : invoquer le 9(2)(h) ne
    #    fait pas sortir du champ de l'article 9, cela rend le traitement de
    #    données sensibles LICITE. Traiter cela comme une exclusion revient à
    #    écarter du périmètre une obligation qui est en réalité respectée —
    #    et le score s'en trouve faussé.
    effet: str = "hors_perimetre"


@dataclass(frozen=True)
class ArticleRGPD:
    numero: str
    intitule: str
    criticite: Criticite
    # Condition d'entrée : si elle n'est pas remplie, l'article est HORS PÉRIMÈTRE
    # et ne compte ni comme conforme ni comme manquement.
    condition_applicabilite: str
    elements_attendus: tuple[ElementProbant, ...]
    derogations: tuple[Derogation, ...] = ()
    note_auditeur: str = ""
    # Quand True, écarter l'article du périmètre exige une citation vérifiée
    # établissant POSITIVEMENT que la condition n'est pas remplie. Le silence
    # du document ne suffit pas. Symétrique de l'exigence de preuve pour la
    # conformité : une exclusion abusive est la faute la plus grave d'un audit.
    exclusion_exige_preuve: bool = True

    @property
    def elements_bloquants(self) -> tuple[ElementProbant, ...]:
        return tuple(e for e in self.elements_attendus if e.bloquant)

    @property
    def derogations_ex_ante(self) -> tuple[Derogation, ...]:
        """Dérogations appréciables sur pièces, hors incident concret."""
        return tuple(d for d in self.derogations if d.evaluable_ex_ante)


def _e(cle: str, intitule: str, *indices: str, bloquant: bool = True) -> ElementProbant:
    return ElementProbant(cle=cle, intitule=intitule, indices=indices, bloquant=bloquant)


# ---------------------------------------------------------------------------
# GRILLE
# ---------------------------------------------------------------------------

REFERENTIEL: tuple[ArticleRGPD, ...] = (
    ArticleRGPD(
        numero="5",
        intitule="Principes relatifs au traitement des données",
        criticite=Criticite.MAJEURE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("finalites", "Finalités déterminées, explicites et légitimes, énoncées pour chaque traitement",
               "finalité", "objet du traitement", "pourquoi"),
            _e("minimisation", "Démonstration que les données collectées sont limitées au nécessaire",
               "minimisation", "données strictement nécessaires", "champs collectés",
               bloquant=False),  # appréciation, rarement documentée explicitement
            _e("duree_conservation", "Durée de conservation chiffrée ou critère de détermination, par catégorie",
               "durée de conservation", "archivage", "purge", "suppression au bout de"),
            _e("exactitude", "Dispositif de mise à jour ou de rectification des données inexactes",
               "mise à jour", "exactitude", "actualisation", bloquant=False),
        ),
        note_auditeur=(
            "Une mention générique du type « nous respectons le RGPD » ne satisfait aucun "
            "élément. Exiger des finalités nommées et des durées chiffrées."
        ),
    ),
    ArticleRGPD(
        numero="6",
        intitule="Licéité du traitement — base légale",
        criticite=Criticite.MAJEURE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("base_identifiee", "Base légale identifiée et nommée pour chaque traitement décrit",
               "consentement", "contrat", "obligation légale", "intérêt légitime", "mission d'intérêt public"),
            _e("adequation", "Cohérence entre la base invoquée et la finalité poursuivie",
               "fondement", "au titre de",
               bloquant=False),  # inférence juridique : ne s'extrait pas d'une citation
            _e("interet_legitime_balance", "Si intérêt légitime invoqué : mise en balance documentée",
               "mise en balance", "test de proportionnalité", "intérêt légitime", bloquant=False),
        ),
        note_auditeur="Invoquer « intérêt légitime » sans balance documentée est un manquement partiel, pas une conformité.",
    ),
    ArticleRGPD(
        numero="7",
        intitule="Conditions applicables au consentement",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite="Au moins un traitement décrit repose sur le consentement.",
        elements_attendus=(
            _e("preuve_consentement",
               "Le mode de recueil du consentement est décrit, ce qui permet d'en rapporter la "
               "preuve : case à cocher non précochée, horodatage, demande écrite signée, "
               "journalisation",
               "preuve du consentement", "horodaté", "case à cocher non précochée",
               "demande écrite", "recueilli par"),
            _e("retrait", "Possibilité de retirer le consentement aussi facilement que de le donner",
               "retrait du consentement", "se désinscrire", "révoquer"),
            _e("libre_specifique",
               "Consentement libre et spécifique : absence de conditionnement du service au "
               "consentement",
               "libre", "spécifique", "sans conséquence", "non conditionné",
               bloquant=False),  # appréciation juridique, rarement énoncée telle quelle
        ),
    ),
    ArticleRGPD(
        numero="9",
        intitule="Traitement de catégories particulières de données",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=(
            "L'organisme traite des données révélant l'origine raciale ou ethnique, les opinions "
            "politiques, les convictions religieuses ou philosophiques, l'appartenance syndicale, "
            "des données génétiques, biométriques aux fins d'identification, de santé, ou "
            "relatives à la vie sexuelle ou l'orientation sexuelle."
        ),
        elements_attendus=(
            _e("fondement_derogatoire", "Identification du fondement de l'article 9(2) autorisant le traitement",
               "consentement explicite", "médecine préventive", "secret professionnel", "santé publique"),
            _e("garanties_renforcees", "Garanties spécifiques : habilitations restreintes, chiffrement, traçabilité des accès",
               "habilitation", "chiffrement", "traçabilité des accès", "secret médical"),
        ),
        derogations=(
            Derogation("9(2)(a)", "Consentement explicite", "La personne a donné son consentement explicite pour une ou plusieurs finalités spécifiques.", effet="conforme"),
            Derogation("9(2)(b)", "Droit du travail et sécurité sociale", "Traitement nécessaire aux obligations en matière de droit du travail, sécurité sociale et protection sociale.", effet="conforme"),
            Derogation("9(2)(c)", "Intérêts vitaux", "Sauvegarde des intérêts vitaux d'une personne physiquement ou juridiquement incapable de consentir.", effet="conforme"),
            Derogation("9(2)(d)", "Organisme à but non lucratif", "Traitement par une fondation, association ou organisme à but non lucratif à finalité politique, philosophique, religieuse ou syndicale, sur ses membres.", effet="conforme"),
            Derogation("9(2)(e)", "Données manifestement rendues publiques", "Les données ont été manifestement rendues publiques par la personne concernée.", effet="conforme"),
            Derogation("9(2)(f)", "Action en justice", "Constatation, exercice ou défense d'un droit en justice.", effet="conforme"),
            Derogation("9(2)(g)", "Intérêt public important", "Motif d'intérêt public important, sur la base du droit de l'Union ou de l'État membre.", effet="conforme"),
            Derogation("9(2)(h)", "Médecine préventive, diagnostic, soins", "Médecine préventive ou du travail, diagnostic médical, prise en charge sanitaire ou sociale, par un professionnel soumis au secret professionnel.", effet="conforme"),
            Derogation("9(2)(i)", "Santé publique", "Motifs d'intérêt public dans le domaine de la santé publique.", effet="conforme"),
            Derogation("9(2)(j)", "Archivage, recherche, statistiques", "Archivage dans l'intérêt public, recherche scientifique ou historique, ou fins statistiques.", effet="conforme"),
        ),
        note_auditeur=(
            "PIÈGE CLASSIQUE. Un cabinet médical, un service de santé au travail ou un "
            "établissement de soins traite des données de santé de manière LICITE au titre "
            "du 9(2)(h). Ne jamais conclure au manquement au seul motif que des données "
            "sensibles sont traitées. La passe de vérification des dérogations est obligatoire."
        ),
    ),
    ArticleRGPD(
        numero="12",
        intitule="Transparence et modalités d'exercice des droits",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("canal_exercice", "Canal identifié et opérationnel pour exercer les droits (adresse, formulaire, contact nommé)",
               "pour exercer vos droits", "adresse", "formulaire", "contact"),
            _e("delai_reponse", "Engagement sur le délai de réponse d'un mois (prorogeable de deux mois)",
               "un mois", "délai de réponse", "sous 30 jours"),
            _e("procedure_interne", "Procédure interne de traitement des demandes : qui reçoit, qui instruit, qui répond",
               "procédure", "traitement des demandes", "responsable du suivi"),
            _e("gratuite", "Gratuité de l'exercice des droits", "gratuit", "sans frais", bloquant=False),
            _e("verification_identite", "Modalité de vérification de l'identité du demandeur",
               "justificatif d'identité", "vérification de l'identité", bloquant=False),
        ),
        note_auditeur=(
            "RÉCIDIVISTE. Mentionner l'existence des droits (art. 13) n'est PAS satisfaire "
            "l'article 12. L'article 12 exige les MODALITÉS : par quel canal, sous quel délai, "
            "avec quelle procédure interne. Une politique qui liste les droits sans dire "
            "comment les exercer est en manquement à l'article 12."
        ),
    ),
    ArticleRGPD(
        numero="13",
        intitule="Information lors d'une collecte directe",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite="L'organisme collecte des données directement auprès des personnes concernées.",
        elements_attendus=(
            _e("identite_responsable", "Identité et coordonnées du responsable de traitement",
               "responsable de traitement", "raison sociale", "siège"),
            _e("coordonnees_dpo", "Coordonnées du DPO lorsqu'il en existe un",
               "délégué à la protection des données", "DPO", "dpo@", bloquant=False),
            _e("finalites_et_base", "Finalités du traitement ET base juridique de chaque finalité",
               "finalité", "base légale", "fondement"),
            _e("destinataires", "Destinataires ou catégories de destinataires des données",
               "destinataires", "transmises à", "prestataires"),
            _e("duree_conservation", "Durée de conservation ou critères de détermination",
               "durée de conservation", "conservées pendant"),
            _e("liste_droits", "Énumération des droits : accès, rectification, effacement, limitation, opposition, portabilité",
               "droit d'accès", "rectification", "effacement", "opposition", "portabilité"),
            _e("droit_reclamation", "Droit d'introduire une réclamation auprès de la CNIL",
               "réclamation", "CNIL", "autorité de contrôle"),
            _e("transferts_hors_ue", "Existence et encadrement d'éventuels transferts hors UE",
               "hors Union européenne", "transfert international", bloquant=False),
        ),
        note_auditeur=(
            "Des mentions légales de site web ne tiennent PAS lieu d'information article 13. "
            "Vérifier élément par élément : l'absence d'un seul élément bloquant suffit à "
            "caractériser le manquement."
        ),
    ),
    ArticleRGPD(
        numero="14",
        intitule="Information lors d'une collecte indirecte",
        criticite=Criticite.MODEREE,
        condition_applicabilite=(
            "L'organisme obtient des données auprès d'un tiers, d'une source publique ou par "
            "achat/location de fichiers, et non directement auprès de la personne concernée."
        ),
        elements_attendus=(
            _e("source_donnees", "Indication de la source dont proviennent les données",
               "source", "obtenues auprès de", "fichier acquis"),
            _e("categories_donnees", "Catégories de données concernées", "catégories de données"),
            _e("delai_information", "Information délivrée dans un délai raisonnable, au plus tard un mois après obtention",
               "dans un délai d'un mois", "lors du premier contact"),
            _e("mentions_communes", "Mentions communes avec l'article 13 (finalités, base, destinataires, durées, droits)",
               "finalité", "droits", "destinataires"),
        ),
        derogations=(
            Derogation("14(5)(a)", "Personne déjà informée", "La personne concernée dispose déjà de ces informations."),
            Derogation("14(5)(b)", "Effort disproportionné", "La fourniture se révèle impossible ou exigerait des efforts disproportionnés, notamment en archivage, recherche ou statistiques, sous réserve de garanties appropriées."),
            Derogation("14(5)(c)", "Obligation légale d'obtention", "L'obtention ou la communication est expressément prévue par le droit de l'Union ou de l'État membre."),
            Derogation("14(5)(d)", "Secret professionnel", "Les données doivent rester confidentielles en vertu d'une obligation de secret professionnel."),
        ),
    ),
    ArticleRGPD(
        numero="15-22",
        intitule="Droits des personnes concernées",
        criticite=Criticite.IMPORTANTE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("acces_portabilite",
               "Un moyen d'extraire les données est indiqué : fonction d'export, format, copie "
               "du dossier, ou toute action décrite. La seule ÉNUMÉRATION du droit d'accès, "
               "sans indication de la manière de l'honorer, ne suffit pas",
               "extraction", "export", "format", "copie des données", "obtenir"),
            _e("effacement",
               "Un moyen de supprimer les données est indiqué : effacement de la fiche, purge, "
               "suppression en base ou en sauvegarde. La seule ÉNUMÉRATION du droit à "
               "l'effacement ne suffit pas",
               "suppression", "effacement", "purge", "sauvegarde"),
            _e("opposition",
               "Une prise en compte de l'opposition ou de la limitation est décrite : liste de "
               "suppression, marqueur, retrait, vérification avant campagne",
               "opposition", "liste de suppression", "limitation", "retrait"),
            _e("tracabilite_demandes", "Registre ou suivi des demandes d'exercice de droits reçues et traitées",
               "registre des demandes", "suivi des demandes", bloquant=False),
        ),
    ),
    ArticleRGPD(
        numero="22",
        intitule="Décision individuelle automatisée, y compris profilage",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=(
            "DEUX conditions cumulatives. (1) La décision produit des effets juridiques ou "
            "affecte significativement la personne : refus de crédit, rejet de candidature, "
            "résiliation, tarification individualisée. (2) Elle est fondée EXCLUSIVEMENT sur un "
            "traitement automatisé, c'est-à-dire sans intervention humaine dotée d'un pouvoir "
            "d'appréciation réel. "
            "HORS PÉRIMÈTRE lorsque le document indique qu'un professionnel examine la "
            "proposition et décide de la suite à donner, ou qu'il peut la modifier : la décision "
            "n'est alors pas exclusivement automatisée. Une alerte, une suggestion, un score "
            "affiché à un opérateur qui tranche ne relèvent pas de l'article 22. "
            "HORS PÉRIMÈTRE également lorsqu'aucun traitement automatisé de décision n'est décrit. "
            "En revanche, un rejet automatique notifié sans qu'un humain n'ait examiné le dossier "
            "relève pleinement de l'article, même si un réexamen peut être demandé ensuite — le "
            "réexamen est alors une GARANTIE au sens du 22(3), pas une cause d'exclusion."
        ),
        elements_attendus=(
            _e("fondement_autorise", "Fondement autorisant la décision automatisée : contrat, disposition légale ou consentement explicite",
               "consentement explicite", "nécessaire au contrat", "autorisé par le droit"),
            _e("intervention_humaine", "Droit d'obtenir une intervention humaine et de contester la décision",
               "intervention humaine", "contester", "réexamen"),
            _e("logique_sous_jacente", "Information sur la logique sous-jacente et les conséquences envisagées",
               "logique sous-jacente", "critères", "fonctionnement de l'algorithme"),
        ),
        note_auditeur=(
            "Une revue humaine purement formelle (validation systématique sans marge "
            "d'appréciation) ne fait pas sortir du champ de l'article 22."
        ),
    ),
    ArticleRGPD(
        numero="25",
        intitule="Protection des données dès la conception et par défaut",
        criticite=Criticite.MODEREE,
        condition_applicabilite="L'organisme développe, paramètre ou déploie des traitements ou outils.",
        elements_attendus=(
            _e("by_design", "Prise en compte de la protection des données en amont des projets",
               "dès la conception", "privacy by design", "en amont"),
            _e("by_default", "Paramétrage par défaut le plus protecteur : durées, accès, visibilité",
               "par défaut", "paramétrage", "accès restreint par défaut"),
        ),
    ),
    ArticleRGPD(
        numero="28",
        intitule="Sous-traitance",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=(
            "L'organisme recourt à des prestataires traitant des données pour son compte "
            "(hébergeur, éditeur SaaS, prestataire de paie, infogérant, cabinet comptable)."
        ),
        elements_attendus=(
            _e("contrat_ecrit", "Contrat ou clauses écrites encadrant chaque sous-traitant",
               "contrat de sous-traitance", "clauses contractuelles", "DPA", "annexe RGPD",
               "prestataire", "sous-traitant", "hébergeur", "destinataires", "transmises à",
               "cabinet comptable", "logiciel", "solution", "opéré par"),
            _e("mentions_obligatoires", "Clauses couvrant : objet, durée, finalité, instructions documentées, confidentialité, sécurité, sort des données en fin de contrat",
               "instructions documentées", "confidentialité", "restitution", "destruction"),
            _e("sous_traitance_ulterieure", "Encadrement de la sous-traitance ultérieure (autorisation préalable)",
               "sous-traitant ultérieur", "autorisation préalable", bloquant=False),
            _e("liste_sous_traitants", "Liste tenue à jour des sous-traitants",
               "liste des sous-traitants", "prestataires", bloquant=False),
        ),
        note_auditeur=(
            "Deux erreurs distinctes à éviter. D'abord, citer le nom d'un hébergeur ou d'un "
            "prestataire ne prouve PAS l'existence de clauses conformes. Ensuite, la seule "
            "mention de destinataires externes — cabinet comptable, assureur, prestataire "
            "informatique, éditeur de logiciel, hébergeur — établit à elle seule que "
            "l'article s'applique : ne jamais écarter la sous-traitance du périmètre au "
            "motif qu'elle ne serait pas mentionnée en tant que telle."
        ),
    ),
    ArticleRGPD(
        numero="30",
        intitule="Registre des activités de traitement",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=(
            "L'organisme compte 250 employés ou plus ; OU le traitement n'est pas occasionnel ; "
            "OU il comporte un risque pour les droits et libertés ; OU il porte sur des données "
            "sensibles ou des condamnations pénales. En pratique, la quasi-totalité des "
            "organismes est concernée : un traitement RH ou clients est par nature non occasionnel."
        ),
        elements_attendus=(
            _e("existence_support", "Existence matérielle du registre et de son support (fichier, outil, document nommé)",
               "registre des traitements", "registre des activités", "tenu à jour dans"),
            _e("liste_traitements", "Énumération des traitements recensés",
               "traitements recensés", "fiche de traitement"),
            _e("mentions_par_traitement", "Pour chaque traitement : finalités, catégories de personnes et de données, destinataires, durées de conservation",
               "finalité", "catégories de données", "destinataires", "durée"),
            _e("mesures_securite",
               "Le registre comporte une description, même générale, des mesures de sécurité. "
               "Une mention indiquant que chaque fiche de traitement documente les mesures de "
               "sécurité satisfait cet élément : l'article 30(1)(g) n'exige qu'une description "
               "générale, pas le détail technique",
               "mesures de sécurité", "mesures techniques et organisationnelles",
               "description des mesures", bloquant=False),
            _e("mise_a_jour", "Preuve de mise à jour : date de dernière révision ou fréquence de revue",
               "mis à jour le", "révision annuelle", "dernière mise à jour"),
        ),
        derogations=(
            Derogation(
                "30(5)", "Dispense partielle petites structures",
                "Organisme de moins de 250 employés, SAUF si le traitement comporte un risque "
                "pour les droits et libertés, s'il n'est pas occasionnel, ou s'il porte sur des "
                "données sensibles ou des condamnations pénales. Ces trois exceptions doivent "
                "être écartées CUMULATIVEMENT. Or tout organisme employant du personnel ou "
                "tenant un fichier clients réalise par nature des traitements non occasionnels : "
                "la dispense est alors inapplicable, quel que soit l'effectif.",
                # Retirée de la passe : le modèle la retenait systématiquement sur le
                # seul critère de l'effectif, produisant des exclusions abusives sur
                # des organismes réellement soumis à l'obligation de registre.
                evaluable_ex_ante=False,
            ),
        ),
        note_auditeur=(
            "RÉCIDIVISTE. Une bonne maturité en sécurité ne présume pas de l'existence du "
            "registre. Exiger une citation nommant le support du registre. Un organisme qui "
            "décrit ses traitements dans une politique de confidentialité n'a pas pour autant "
            "un registre au sens de l'article 30. Ne jamais retenir la dispense 30(5) au seul "
            "motif de l'effectif."
        ),
    ),
    ArticleRGPD(
        numero="32",
        intitule="Sécurité du traitement",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("controle_acces", "Gestion des accès : comptes nominatifs, habilitations, revue périodique",
               "habilitation", "comptes nominatifs", "gestion des accès", "authentification"),
            _e("chiffrement", "Chiffrement ou pseudonymisation adaptés aux données traitées",
               "chiffrement", "chiffré", "pseudonymisation", "TLS", "au repos"),
            _e("sauvegardes", "Sauvegardes et capacité de restauration testée",
               "sauvegarde", "restauration", "PRA", "test de restauration"),
            _e("tracabilite", "Journalisation des accès et des actions sensibles",
               "journalisation", "logs", "traçabilité"),
            _e("revue_securite", "Procédure de test et d'évaluation régulière des mesures",
               "audit de sécurité", "test d'intrusion", "revue annuelle", bloquant=False),
        ),
    ),
    ArticleRGPD(
        numero="33",
        intitule="Notification d'une violation à l'autorité de contrôle",
        criticite=Criticite.MAJEURE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("procedure_ecrite", "Procédure écrite de gestion des violations de données",
               "procédure de violation", "incident de sécurité", "gestion des violations"),
            _e("delai_72h", "Mention explicite du délai de 72 heures",
               "72 heures", "soixante-douze heures", "trois jours"),
            _e("destinataire_cnil", "Identification de la CNIL comme destinataire de la notification",
               "CNIL", "autorité de contrôle", "notification à l'autorité"),
            _e("registre_violations", "Registre interne documentant toute violation, y compris non notifiée",
               "registre des violations", "documentation des violations"),
            _e("role_responsable", "Désignation de qui déclenche et pilote la notification",
               "responsable de la notification", "qui alerte", bloquant=False),
        ),
        note_auditeur=(
            "RÉCIDIVISTE. Disposer d'un antivirus, d'un pare-feu ou d'une politique de "
            "sécurité solide ne satisfait EN RIEN l'article 33. L'article 33 porte sur une "
            "procédure de NOTIFICATION, pas sur la prévention. En l'absence de citation "
            "mentionnant le délai de 72 heures ou la notification à la CNIL, le verdict est "
            "manquement, quelle que soit la maturité affichée en sécurité."
        ),
    ),
    ArticleRGPD(
        numero="34",
        intitule="Communication d'une violation à la personne concernée",
        criticite=Criticite.MODEREE,
        condition_applicabilite="L'organisme traite des données à caractère personnel.",
        elements_attendus=(
            _e("critere_risque_eleve",
               "Le déclenchement de l'information des personnes est lié au risque élevé pour "
               "leurs droits et libertés",
               "risque élevé", "information des personnes concernées"),
            _e("modalite_communication",
               "La manière dont les personnes sont informées est indiquée, même brièvement : "
               "individuellement, par courriel, par courrier, par communication publique. Une "
               "phrase du type « les personnes concernées sont informées individuellement » "
               "satisfait cet élément",
               "informées individuellement", "courriel", "courrier", "communication publique",
               "dans les meilleurs délais"),
        ),
        derogations=(
            Derogation("34(3)(a)", "Données rendues incompréhensibles", "Mesures de protection appropriées appliquées, notamment un chiffrement rendant les données incompréhensibles.", evaluable_ex_ante=False),
            Derogation("34(3)(b)", "Mesures ultérieures", "Mesures ultérieures garantissant que le risque élevé n'est plus susceptible de se matérialiser.", evaluable_ex_ante=False),
            Derogation("34(3)(c)", "Effort disproportionné", "La communication individuelle exigerait des efforts disproportionnés ; une communication publique est alors substituée.", evaluable_ex_ante=False),
        ),
    ),
    ArticleRGPD(
        numero="35",
        intitule="Analyse d'impact relative à la protection des données",
        criticite=Criticite.MAJEURE,
        condition_applicabilite=(
            "Le traitement est susceptible d'engendrer un risque élevé : évaluation systématique "
            "et approfondie d'aspects personnels fondée sur un traitement automatisé, traitement "
            "à grande échelle de données sensibles, surveillance systématique à grande échelle "
            "d'une zone accessible au public, ou correspondance avec la liste CNIL des "
            "traitements soumis à AIPD."
        ),
        elements_attendus=(
            _e("aipd_realisee", "AIPD réalisée et datée pour les traitements à risque élevé",
               "analyse d'impact", "AIPD", "DPIA", "PIA"),
            _e("contenu_aipd", "Description systématique, évaluation de la nécessité et de la proportionnalité, analyse des risques, mesures envisagées",
               "risques identifiés", "proportionnalité", "mesures de réduction"),
            _e("avis_dpo", "Avis du DPO sollicité", "avis du délégué", "consultation du DPO", bloquant=False),
        ),
    ),
    ArticleRGPD(
        numero="37",
        intitule="Désignation d'un délégué à la protection des données",
        criticite=Criticite.IMPORTANTE,
        # L'exigence de citation prouvant la non-applicabilité, protectrice
        # ailleurs, est ici une impossibilité logique. Elle fonctionne pour les
        # articles 44-49, qu'un document écarte par une affirmation positive
        # (« aucune donnée n'est transférée hors de l'Union »). Aucun organisme
        # n'écrit en revanche que ses activités de base n'impliquent pas de
        # suivi à grande échelle : on lui demanderait de citer la preuve d'une
        # absence. L'applicabilité se déduit ici des caractéristiques décrites
        # (effectif, secteur, nature de l'activité), que le modèle lit dans le
        # document sans avoir à en citer la négation.
        exclusion_exige_preuve=False,
        condition_applicabilite=(
            "CE QUI REND L'ARTICLE APPLICABLE — au moins une des trois conditions : (1) organisme "
            "public ou autorité publique ; (2) les ACTIVITÉS DE BASE exigent un suivi régulier et "
            "systématique à grande échelle des personnes — vidéoprotection d'un lieu public très "
            "fréquenté, profilage publicitaire, scoring, plateforme de mise en relation, "
            "géolocalisation de flottes ; (3) les ACTIVITÉS DE BASE consistent en un traitement à "
            "grande échelle de données sensibles ou de condamnations pénales — établissement de "
            "santé, laboratoire, assureur santé. "
            "CE QUI REND L'ARTICLE HORS PÉRIMÈTRE — aucune des trois conditions n'est remplie. La "
            "désignation est alors facultative, et le verdict attendu est HORS PÉRIMÈTRE, jamais "
            "manquement. "
            "QUELLE CITATION CHERCHER. La phrase qui renseigne cette condition est celle qui DÉCRIT "
            "L'ACTIVITÉ DE BASE de l'organisme : « boulangerie-pâtisserie artisanale », « entreprise "
            "artisanale de menuiserie », « cabinet de conseil en organisation », « organisme de "
            "formation professionnelle ». Cette description suffit et constitue la citation "
            "attendue. N'attends PAS une phrase qui nierait explicitement l'obligation : aucun "
            "organisme n'écrit que ses activités de base n'impliquent pas de suivi à grande "
            "échelle. Exiger une telle négation reviendrait à rendre l'exclusion impossible. "
            "COMMENT CONCLURE. Confronte l'activité citée aux trois conditions. Si elle n'entre "
            "manifestement dans aucune, conclus \"applicable\": false — c'est la bonne réponse, pas "
            "une prise de risque. Si le document ne décrit aucune activité, conclus true. "
            "L'EFFECTIF N'EST PAS UN CRITÈRE. Vingt personnes dont le métier est le profilage "
            "publicitaire sont soumises à l'obligation ; mille salariés en distribution alimentaire "
            "ne le sont pas. « Activités de base » désigne le coeur de métier, jamais les fonctions "
            "support : la gestion RH ou la paie n'en sont pas. "
            "DEUX RÈGLES QUI L'EMPORTENT SUR TOUT. (a) Si le document mentionne un DPO désigné, "
            "l'article est APPLICABLE. (b) Si le document décrit un profilage, un scoring, une "
            "vidéoprotection étendue, une présélection automatisée de candidatures ou un traitement "
            "de données sensibles, l'article est APPLICABLE — quel que soit le secteur affiché."),
        elements_attendus=(
            _e("designation", "DPO désigné et identifié (interne ou externe)",
               "délégué à la protection des données", "DPO désigné"),
            _e("coordonnees_publiees", "Coordonnées du DPO publiées et communiquées à la CNIL",
               "dpo@", "coordonnées du délégué", "déclaré à la CNIL"),
            _e("independance_moyens", "Positionnement garantissant l'absence de conflit d'intérêts et les moyens d'exercer",
               "rattaché à la direction", "sans conflit d'intérêts", "moyens", bloquant=False),
        ),
        note_auditeur=(
            "Un artisan ou une TPE sans traitement à grande échelle n'a AUCUNE obligation de "
            "désigner un DPO. Verdict attendu : hors périmètre, jamais manquement."
        ),
    ),
    ArticleRGPD(
        numero="44-49",
        intitule="Transferts de données hors Union européenne",
        criticite=Criticite.CRITIQUE,
        condition_applicabilite=(
            "Des données sont transférées, hébergées, accessibles ou traitées depuis un pays "
            "tiers à l'Union européenne, y compris via un prestataire américain ou un accès "
            "support depuis un pays tiers."
        ),
        elements_attendus=(
            _e("identification_transferts", "Identification des transferts, du pays de destination et du prestataire concerné",
               "hors Union européenne", "États-Unis", "pays tiers", "hébergé aux"),
            _e("outil_transfert", "Outil de transfert valide : décision d'adéquation, clauses contractuelles types, BCR",
               "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
            _e("mesures_supplementaires", "Analyse d'impact du transfert et mesures supplémentaires le cas échéant",
               "mesures supplémentaires", "analyse du transfert", "chiffrement", bloquant=False),
        ),
        note_auditeur=(
            "Le recours à un prestataire de cloud non européen sans mention d'un outil de "
            "transfert est un manquement caractérisé, quelle que soit la qualité du reste du "
            "dispositif."
        ),
    ),
)


PAR_NUMERO: dict[str, ArticleRGPD] = {a.numero: a for a in REFERENTIEL}


def article(numero: str) -> ArticleRGPD:
    try:
        return PAR_NUMERO[numero]
    except KeyError as exc:
        raise KeyError(
            f"Article {numero!r} absent du référentiel. Articles couverts : "
            f"{', '.join(PAR_NUMERO)}"
        ) from exc


def resume_referentiel() -> str:
    lignes = [f"{len(REFERENTIEL)} articles couverts", ""]
    for a in REFERENTIEL:
        lignes.append(
            f"  art. {a.numero:<8} {a.intitule[:52]:<54} "
            f"crit={a.criticite.value}  éléments={len(a.elements_attendus)} "
            f"(bloquants={len(a.elements_bloquants)})  dérogations={len(a.derogations)}"
        )
    return "\n".join(lignes)


if __name__ == "__main__":
    print(resume_referentiel())
