"""Mots-cles de recherche par exigence, par referentiel -- copie adaptee des
`indices` de `referentiel/articles.py` et `referentiel/articles_{nis2,dora,
ai_act}.py` (grilles du LABORATOIRE, voir docs/architecture.md DA-07/DA-10).

Seuls les indices des elements BLOQUANTS (`ElementProbant.bloquant=True`)
sont repris : un element non bloquant (ex. article 37 RGPD,
"independance_moyens") est un signal secondaire dans la grille du
laboratoire -- ses mots-cles y sont trop generiques pour orienter une
recherche seuls ("moyens", "direction" dans "rattache a la direction").
Mesure en conditions reelles (2026-09-28) : les inclure a cause une
exclusion abusive (article 37, doc 15 du corpus RGPD -- "direction technique"
dans un contexte de securite IT matche a tort "rattache a la direction").

Le backend n'importe jamais le paquet `referentiel` ni `evaluation` (deux
paquets separes, voir docs/architecture.md) : cette copie statique, generee
une fois par extraction des `indices`, est le seul lien entre les deux
cotes. Toute mise a jour d'une grille du laboratoire doit etre reportee ici
a la main -- meme regle deja appliquee a
`app/services/rag.py::_scores_lexicaux` (copie de l'algorithme de retrieval).

Les groupes d'articles de la grille RGPD ("15-22", "44-49") sont deplies : le
meme jeu de mots-cles s'applique a chaque article individuel du groupe, car
la production evalue chaque article separement (un Requirement par article
ingere depuis EUR-Lex), contrairement au laboratoire qui evalue le groupe
comme une seule unite.

Usage : voir audit_engine.py::run_audit, phase 1 -- ces mots-cles enrichissent
la requete de recherche de passages (`rag.search_client_documents`) en plus
du texte legal de l'exigence, jamais a sa place : le texte legal reste un
repli garanti si un article n'a pas (encore) de mots-cles ici.
"""

from __future__ import annotations

MOTS_CLES: dict[str, dict[int, tuple[str, ...]]] = {
    "rgpd": {
        5: ("finalité", "objet du traitement", "pourquoi", "durée de conservation", "archivage", "purge", "suppression au bout de"),
        6: ("consentement", "contrat", "obligation légale", "intérêt légitime", "mission d'intérêt public"),
        7: ("preuve du consentement", "horodaté", "case à cocher non précochée", "demande écrite", "recueilli par", "retrait du consentement", "se désinscrire", "révoquer"),
        9: ("consentement explicite", "médecine préventive", "secret professionnel", "santé publique", "habilitation", "chiffrement", "traçabilité des accès", "secret médical"),
        12: ("pour exercer vos droits", "adresse", "formulaire", "contact", "un mois", "délai de réponse", "sous 30 jours", "procédure", "traitement des demandes", "responsable du suivi"),
        13: ("responsable de traitement", "raison sociale", "siège", "finalité", "base légale", "fondement", "destinataires", "transmises à", "prestataires", "durée de conservation", "conservées pendant", "droit d'accès", "rectification", "effacement", "opposition", "portabilité", "réclamation", "CNIL", "autorité de contrôle"),
        14: ("source", "obtenues auprès de", "fichier acquis", "catégories de données", "dans un délai d'un mois", "lors du premier contact", "finalité", "droits", "destinataires"),
        15: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        16: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        17: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        18: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        19: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        20: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        21: ("extraction", "export", "format", "copie des données", "obtenir", "suppression", "effacement", "purge", "sauvegarde", "opposition", "liste de suppression", "limitation", "retrait"),
        22: ("consentement explicite", "nécessaire au contrat", "autorisé par le droit", "intervention humaine", "contester", "réexamen", "logique sous-jacente", "critères", "fonctionnement de l'algorithme"),
        25: ("dès la conception", "privacy by design", "en amont", "par défaut", "paramétrage", "accès restreint par défaut"),
        28: ("contrat de sous-traitance", "clauses contractuelles", "DPA", "annexe RGPD", "prestataire", "sous-traitant", "hébergeur", "destinataires", "transmises à", "cabinet comptable", "logiciel", "solution", "opéré par", "instructions documentées", "confidentialité", "restitution", "destruction"),
        30: ("registre des traitements", "registre des activités", "tenu à jour dans", "traitements recensés", "fiche de traitement", "finalité", "catégories de données", "destinataires", "durée", "mis à jour le", "révision annuelle", "dernière mise à jour"),
        32: ("habilitation", "comptes nominatifs", "gestion des accès", "authentification", "chiffrement", "chiffré", "pseudonymisation", "TLS", "au repos", "sauvegarde", "restauration", "PRA", "test de restauration", "journalisation", "logs", "traçabilité"),
        33: ("procédure de violation", "incident de sécurité", "gestion des violations", "72 heures", "soixante-douze heures", "trois jours", "CNIL", "autorité de contrôle", "notification à l'autorité", "registre des violations", "documentation des violations"),
        34: ("risque élevé", "information des personnes concernées", "informées individuellement", "courriel", "courrier", "communication publique", "dans les meilleurs délais"),
        35: ("analyse d'impact", "AIPD", "DPIA", "PIA", "risques identifiés", "proportionnalité", "mesures de réduction"),
        37: ("délégué à la protection des données", "DPO désigné", "dpo@", "coordonnées du délégué", "déclaré à la CNIL"),
        44: ("hors Union européenne", "États-Unis", "pays tiers", "hébergé aux", "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
        45: ("hors Union européenne", "États-Unis", "pays tiers", "hébergé aux", "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
        46: ("hors Union européenne", "États-Unis", "pays tiers", "hébergé aux", "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
        47: ("hors Union européenne", "États-Unis", "pays tiers", "hébergé aux", "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
        48: ("hors Union européenne", "États-Unis", "pays tiers", "hébergé aux", "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
        49: ("hors Union européenne", "États-Unis", "pays tiers", "hébergé aux", "décision d'adéquation", "clauses contractuelles types", "CCT", "BCR", "Data Privacy Framework"),
    },
    "nis2": {
        20: ("approuve", "conseil de direction", "conseil d'administration", "formation", "sensibilisation", "membres du conseil", "responsable de la sécurité", "DSIS", "RSSI", "rattaché"),
        21: ("analyse de risques", "politique de sécurité", "cartographie des risques", "gestion des incidents", "procédure d'incident", "astreinte", "plan de continuité", "reprise après sinistre", "exercice de crise", "sauvegarde", "chaîne d'approvisionnement", "clause de sécurité", "contrat fournisseur", "prestataire", "authentification multifacteurs", "hygiène informatique", "gestion des correctifs", "mots de passe"),
        23: ("notification d'incident", "CSIRT", "autorité compétente", "alerte précoce", "24 heures", "rapport final", "un mois"),
        24: ("certification européenne", "schéma de certification", "certifié"),
        27: ("registre des entités", "enregistré auprès de", "ENISA"),
        28: ("données d'enregistrement", "base de données", "titulaire du nom de domaine", "vérification des données", "procédure de vérification"),
        29: ("partage d'informations", "dispositif sectoriel", "indicateurs de compromission"),
        30: ("notification volontaire", "cybermenace", "quasi-incident", "tentative d'intrusion"),
    },
    "dora": {
        5: ("conseil d'administration", "approuve", "responsabilité", "responsable des risques TIC", "comité des risques", "rattaché"),
        6: ("cadre de gestion du risque", "stratégie de résilience", "politique de sécurité de l'information", "revu chaque année", "audit interne", "mise à jour"),
        7: ("inventaire", "composants critiques", "plan de remplacement"),
        8: ("cartographie des actifs", "fonctions critiques", "dépendances"),
        9: ("chiffrement", "chiffrées", "moindre privilège", "authentification multifacteurs", "habilitations"),
        10: ("détection des anomalies", "supervision", "SOC", "surveillance continue"),
        11: ("plan de réponse aux incidents", "procédure d'incident", "plan de continuité d'activité", "exercice de crise", "testé"),
        12: ("politique de sauvegarde", "sauvegardes quotidiennes", "chiffrées", "test de restauration", "compte-rendu"),
        13: ("retour d'expérience", "registre des enseignements", "sensibilisation", "formation", "campagne"),
        14: ("plan de communication de crise", "communication de crise"),
        16: ("cadre simplifié", "éligible"),
        17: ("processus de gestion des incidents", "qualification", "escalade"),
        18: ("critères de classification", "gravité", "criticité des services"),
        19: ("notification à l'autorité", "notification initiale", "rapport final", "délai", "transmis dans les délais", "sous 24 heures"),
        22: ("retour de l'autorité", "actions correctives", "comité des risques"),
        23: ("incidents liés au paiement", "moyens de paiement", "régime spécifique"),
        24: ("programme de tests", "résilience opérationnelle numérique"),
        25: ("test de vulnérabilité", "analyse de la sécurité des réseaux"),
        26: ("test de pénétration fondé sur la menace", "TLPT", "TIBER-EU"),
        27: ("testeurs accrédités", "assurance responsabilité civile"),
        28: ("stratégie relative au risque", "prestataires tiers", "registre des contrats", "accords contractuels"),
        29: ("risque de concentration", "prestataires critiques"),
        30: ("clause d'audit", "stratégie de sortie", "réversibilité", "localisation des données", "protection des données"),
    },
    "ai_act": {
        5: ("aucune pratique interdite", "absence de notation sociale", "aucune technique subliminale"),
        8: ("dossier de conformité", "respect systématique"),
        9: ("système de gestion des risques", "identification des risques", "mesures d'atténuation"),
        10: ("gouvernance des données", "audit de biais", "représentativité"),
        11: ("documentation technique", "annexe IV", "mise à jour"),
        12: ("journaux générés automatiquement", "traçabilité"),
        13: ("notice d'utilisation", "instructions", "limites de performance"),
        14: ("contrôle humain", "supervision humaine", "validation par un opérateur", "fonction d'interruption"),
        15: ("métriques de précision", "robustesse", "tests de résistance"),
        16: ("obligations du fournisseur", "pilotage qualité"),
        17: ("système de gestion de la qualité", "SGQ"),
        18: ("conservation", "dix ans"),
        19: ("conservation des journaux", "durée appropriée"),
        20: ("mesures correctives", "retrait", "rappel", "information des autorités"),
        21: ("contact désigné", "coopération avec les autorités"),
        22: ("mandataire", "mandat écrit"),
        23: ("importateur", "vérification avant mise sur le marché"),
        24: ("distributeur", "vérification"),
        25: ("chaîne de valeur", "transfert des obligations", "modification substantielle"),
        26: ("contrôle humain", "surveillance du système", "formation des utilisateurs", "information des personnes concernées", "décision automatisée"),
        27: ("analyse d'impact", "droits fondamentaux"),
        47: ("déclaration UE de conformité", "signée"),
        48: ("marquage CE", "apposé"),
        49: ("base de données de l'Union", "enregistré", "enregistrement"),
        50: ("assistant automatisé", "contenu généré par IA", "hypertrucage", "divulgation"),
        72: ("surveillance après commercialisation", "retours d'utilisation"),
        73: ("signalement d'incidents graves", "délai"),
        86: ("droit à l'explication", "explication individuelle", "sans retard indu"),
    },
}

