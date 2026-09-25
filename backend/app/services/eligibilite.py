"""
Filtre d'eligibilite pour les exigences a applicabilite conditionnelle.

Probleme traite
---------------
La non-applicabilite d'une exigence est aujourd'hui decidee par le verdict
LLM/heuristique, a partir des seuls passages du document client. Or certaines
obligations dependent du profil de l'organisme (effectif, secteur, nature des
donnees) et non du contenu documentaire : le modele ne peut pas savoir que le
client a trois salaries si l'information ne figure dans aucun passage.

Sur le corpus de validation (15 documents, 210 articles), les articles 30, 37
et 13 du RGPD representaient 13 des 17 faux positifs. Ce module les tranche en
amont, de maniere deterministe et tracable.

Principe de prudence
--------------------
Trois verdicts, jamais deux. Une information manquante ne produit JAMAIS une
exemption : elle produit A_VERIFIER, qui laisse l'exigence suivre le parcours
d'evaluation normal. Le cout d'un faux negatif (obligation manquee, sanction)
est sans commune mesure avec celui d'un faux positif.

Indexation par referentiel
--------------------------
Les regles sont clees sur (framework, numero d'article). L'article 30 du RGPD
est le registre des traitements ; l'article 30 de NIS2 ou de la CSRD n'a aucun
rapport. Une regle non indexee par referentiel produirait des exemptions
absurdes des le premier audit multi-referentiel.

Tableau de correspondance -- NIS2, DORA, AI Act (verifie article par article
sur le texte reellement ingere, pas seulement sur les intitules)
------------------------------------------------------------------
Verifie en relisant le corps de chaque article auditable (voir
app/ingestion/scoping.py pour la liste). Plusieurs corrections ont ete
apportees a la proposition initiale :

| Referentiel | Articles | Condition d'exemption | Fondement |
|---|---|---|---|
| NIS2 | 20, 21, 23, 24, 29, 30 | `entite_nis2 == "non_concernee"` | NIS2, art. 2 et 3 |
| NIS2 | 27, 28 | idem, MAIS `entite_nis2` essentielle/importante ne suffit PAS a conclure a l'applicabilite (voir correction ci-dessous) | NIS2, art. 27 et 28 |
| DORA | 5-14, 16-19, 22, 24-30 | `entite_financiere_dora is False` | DORA, art. 2 |
| DORA | 15, 20, 21 | toujours exempte (voir correction ci-dessous) | -- |
| DORA | 23 | idem 5-30, MAIS `entite_financiere_dora=True` ne suffit pas (voir correction) | DORA, art. 23 |
| AI Act | 5 | jamais exempte | AI Act, art. 5 |
| AI Act | 50 | `ia_utilisee is False` | AI Act, art. 50 |
| AI Act | 8-22, 25, 47-49, 72, 73 | `ia_fournisseur_haut_risque is False` | AI Act, art. 6 et 16 |
| AI Act | 23, 24 | aucune regle (voir correction ci-dessous) | -- |
| AI Act | 26 | `ia_deployeur_haut_risque is False` | AI Act, art. 26 |
| AI Act | 27, 86 | idem 26, MAIS `True` ne suffit pas (voir correction) | AI Act, art. 27 et 86 |

Corrections apportees a la proposition initiale, chacune verifiee en lisant
le corps de l'article (pas seulement son intitule) :

1. **NIS2 art. 27 et 28** ne visent pas "toute entite essentielle ou
   importante" : l'art. 27 charge l'ENISA de tenir un registre "des
   fournisseurs de services DNS, des registres des noms de domaine de
   premier niveau, des entites qui fournissent des services d'enregistrement
   de noms de domaine..." et l'art. 28 impose des obligations aux "registres
   des noms de domaine de premier niveau et aux entites fournissant des
   services d'enregistrement de noms de domaine" -- un role beaucoup plus
   etroit que le statut general d'entite essentielle/importante. Aucun champ
   de profil ne capture ce role precis : `entite_nis2` en essentielle ou
   importante ne suffit donc pas a conclure a l'applicabilite (A_VERIFIER),
   seule l'absence de tout statut NIS2 exempte avec certitude.

2. **DORA art. 23** ne vise que "les etablissements de credit, les
   etablissements de paiement, les prestataires de services d'information
   sur les comptes et les etablissements de monnaie electronique" -- pas
   toute entite financiere au sens large de l'art. 2 (qui couvre aussi les
   assurances, entreprises d'investissement, prestataires de services sur
   crypto-actifs, etc.). Meme traitement de prudence que NIS2 27/28.

3. **DORA art. 15, 20 et 21** sont en realite des obligations des AES
   (autorites europeennes de surveillance) -- "Les AES elaborent, par
   l'intermediaire du comite mixte..." -- pas de l'entite financiere
   elle-meme. Comparable aux articles institutionnels deja exclus du
   perimetre auditable du RGPD (51-99) : toujours exemptes, quel que soit le
   profil. Ce sont des articles de la liste blanche `DORA_AUDITABLE`
   (app/ingestion/scoping.py) qui, a la lecture, n'auraient pas du y figurer ;
   corrige ici par le filtre d'eligibilite plutot qu'en modifiant la liste
   blanche, hors perimetre de cette tache.

4. **AI Act art. 27** (analyse d'impact sur les droits fondamentaux) et
   **art. 86** (droit a l'explication) ne visent qu'un sous-ensemble des
   deployeurs de systemes a haut risque : l'art. 27 se limite aux
   "organismes de droit public", aux "entites privees fournissant des
   services publics" et aux deployeurs de systemes d'evaluation de la
   solvabilite/du risque d'assurance (annexe III, points 5 b et c) ; l'art. 86
   ne s'applique qu'aux decisions "produisant des effets juridiques" ou
   affectant significativement une personne. `ia_deployeur_haut_risque=True`
   ne suffit donc pas a conclure a l'applicabilite (A_VERIFIER) ; seul `False`
   exempte avec certitude.

5. **AI Act art. 23 et 24** (obligations des importateurs et des
   distributeurs) relevent d'un role distinct de celui du fournisseur --
   un importateur ou distributeur n'est pas necessairement le fournisseur
   (developpeur) du systeme. Aucun champ de profil dedie n'existe pour ce
   role precis (en ajouter un sortirait du perimetre des cinq colonnes
   prevues pour cette tache) : ces deux articles ne recoivent aucune regle
   et restent APPLICABLE par defaut, comme tout article hors de cette table.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Protocol


class Verdict(str, Enum):
    APPLICABLE = "applicable"      # l'exigence est evaluee normalement
    EXEMPTE = "exempte"            # exemption certaine, sortie du perimetre
    A_VERIFIER = "a_verifier"      # profil incomplet, evaluation maintenue


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    justification: str
    reference: str

    @property
    def conserver(self) -> bool:
        """Une exigence n'est ecartee que si l'exemption est certaine."""
        return self.verdict is not Verdict.EXEMPTE


@dataclass
class ProfilOrganisme:
    """
    Profil de l'organisation auditee.

    Tous les champs sont optionnels : None signifie "non renseigne" et conduit
    systematiquement a A_VERIFIER plutot qu'a une exemption.
    """
    effectif: int | None = None
    organisme_public: bool | None = None

    # Article 9 : origine raciale ou ethnique, opinions politiques, convictions
    # religieuses, appartenance syndicale, genetique, biometrie, sante, vie
    # sexuelle. Article 10 : condamnations penales et infractions.
    donnees_sensibles_art9: bool | None = None
    donnees_penales_art10: bool | None = None

    # Notions de l'article 37 : activite de base, suivi regulier et
    # systematique, grande echelle.
    activite_de_base_traitement: bool | None = None
    suivi_regulier_systematique: bool | None = None
    grande_echelle: bool | None = None

    # Considerant 91 : le traitement par un professionnel de sante ou un avocat
    # exercant a titre individuel n'est pas "a grande echelle".
    professionnel_liberal_isole: bool | None = None

    # Article 30(5) : l'exemption suppose un traitement occasionnel et sans
    # risque pour les droits et libertes.
    traitement_occasionnel: bool | None = None
    risque_droits_libertes: bool | None = None

    # Articles 13 / 14 : collecte directe aupres de la personne concernee (13)
    # ou indirecte, aupres d'un tiers (14).
    collecte_directe: bool | None = None
    collecte_indirecte: bool | None = None

    # NIS2 : statut au sens des art. 2 et 3. "essentielle" | "importante" |
    # "non_concernee" | None (non renseigne -> A_VERIFIER).
    entite_nis2: str | None = None

    # DORA : entite financiere au sens de l'art. 2.
    entite_financiere_dora: bool | None = None

    # AI Act : fournisseur ou deployeur d'un systeme d'IA a haut risque
    # (art. 6 et 16 pour le premier, art. 26 pour le second), et usage d'un
    # systeme d'IA quelconque (art. 50, transparence -- independant du
    # niveau de risque).
    ia_fournisseur_haut_risque: bool | None = None
    ia_deployeur_haut_risque: bool | None = None
    ia_utilisee: bool | None = None


class ExigenceLike(Protocol):
    """Contrat minimal attendu d'un Requirement SQLAlchemy."""
    reference: str


# --------------------------------------------------------------------------
# Regles RGPD
# --------------------------------------------------------------------------

def _rgpd_art30(p: ProfilOrganisme) -> Decision:
    """
    Article 30(5) : dispense de registre pour les organismes de moins de
    250 salaries, SAUF si le traitement (a) est susceptible de comporter un
    risque pour les droits et libertes, (b) n'est pas occasionnel, ou
    (c) porte sur des donnees des articles 9 ou 10.

    Les trois exceptions sont alternatives : une seule suffit a retablir
    l'obligation. La CNIL rappelle que la dispense est en pratique tres etroite.
    """
    ref = "RGPD art. 30(5)"

    if p.effectif is None:
        return Decision(Verdict.A_VERIFIER, "Effectif non renseigne : dispense indecidable.", ref)

    if p.effectif >= 250:
        return Decision(Verdict.APPLICABLE, f"Effectif de {p.effectif} salaries (>= 250) : aucune dispense.", ref)

    if p.donnees_sensibles_art9:
        return Decision(Verdict.APPLICABLE, "Traitement de donnees sensibles (art. 9) : dispense ecartee.", ref)
    if p.donnees_penales_art10:
        return Decision(Verdict.APPLICABLE, "Traitement de donnees penales (art. 10) : dispense ecartee.", ref)
    if p.risque_droits_libertes:
        return Decision(Verdict.APPLICABLE, "Risque pour les droits et libertes : dispense ecartee.", ref)
    if p.traitement_occasionnel is False:
        return Decision(Verdict.APPLICABLE, "Traitement non occasionnel (paie, clients recurrents) : dispense ecartee.", ref)

    manquants = [
        libelle for libelle, valeur in (
            ("caractere occasionnel du traitement", p.traitement_occasionnel),
            ("risque pour les droits et libertes", p.risque_droits_libertes),
            ("presence de donnees sensibles", p.donnees_sensibles_art9),
        ) if valeur is None
    ]
    if manquants:
        return Decision(
            Verdict.A_VERIFIER,
            f"Effectif < 250 mais information manquante : {', '.join(manquants)}.",
            ref,
        )

    return Decision(
        Verdict.EXEMPTE,
        f"Effectif de {p.effectif} salaries, traitement occasionnel, sans risque pour les "
        f"droits et libertes ni donnees sensibles : dispense de registre applicable.",
        ref,
    )


def _rgpd_art37(p: ProfilOrganisme) -> Decision:
    """
    Article 37(1) : DPO obligatoire dans trois cas alternatifs.
      (a) autorite publique ou organisme public ;
      (b) activites de base impliquant un suivi regulier et systematique des
          personnes a grande echelle ;
      (c) activites de base impliquant un traitement a grande echelle de
          donnees des articles 9 ou 10.

    Considerant 91 : le professionnel de sante ou l'avocat exercant a titre
    individuel ne releve pas de la grande echelle, meme s'il traite des donnees
    de sante.
    """
    ref = "RGPD art. 37(1), considerant 91"

    if p.organisme_public:
        return Decision(Verdict.APPLICABLE, "Organisme public : DPO obligatoire (art. 37(1)(a)).", ref)

    if p.professionnel_liberal_isole:
        return Decision(
            Verdict.EXEMPTE,
            "Professionnel exercant a titre individuel : traitement non constitutif d'une "
            "grande echelle (considerant 91). DPO non obligatoire, designation volontaire possible.",
            ref,
        )

    if p.organisme_public is None:
        return Decision(Verdict.A_VERIFIER, "Nature publique ou privee de l'organisme non renseignee.", ref)

    if p.grande_echelle is False:
        return Decision(
            Verdict.EXEMPTE,
            "Organisme prive et traitement hors grande echelle : aucun des trois cas de "
            "l'article 37(1) n'est constitue.",
            ref,
        )

    if p.grande_echelle:
        if p.activite_de_base_traitement is False:
            return Decision(
                Verdict.EXEMPTE,
                "Traitement a grande echelle mais ne relevant pas de l'activite de base : "
                "l'article 37(1)(b) et (c) exige que le traitement constitue l'activite "
                "principale de l'organisme.",
                ref,
            )
        if p.suivi_regulier_systematique:
            return Decision(Verdict.APPLICABLE, "Suivi regulier et systematique a grande echelle (art. 37(1)(b)).", ref)
        if p.donnees_sensibles_art9 or p.donnees_penales_art10:
            return Decision(Verdict.APPLICABLE, "Donnees des art. 9 ou 10 traitees a grande echelle (art. 37(1)(c)).", ref)
        if p.activite_de_base_traitement is None:
            return Decision(Verdict.A_VERIFIER, "Grande echelle averee mais activite de base non qualifiee.", ref)
        return Decision(
            Verdict.EXEMPTE,
            "Grande echelle sans suivi systematique ni donnees sensibles : aucun cas de "
            "l'article 37(1) constitue.",
            ref,
        )

    return Decision(Verdict.A_VERIFIER, "Caractere de grande echelle du traitement non qualifie.", ref)


def _rgpd_art13(p: ProfilOrganisme) -> Decision:
    """Article 13 : information due en cas de collecte aupres de la personne concernee."""
    ref = "RGPD art. 13 (vs art. 14)"
    if p.collecte_directe:
        return Decision(Verdict.APPLICABLE, "Collecte directe aupres des personnes concernees.", ref)
    if p.collecte_directe is False and p.collecte_indirecte:
        return Decision(
            Verdict.EXEMPTE,
            "Collecte exclusivement indirecte : l'obligation d'information releve de "
            "l'article 14, non de l'article 13.",
            ref,
        )
    return Decision(Verdict.A_VERIFIER, "Source de collecte non renseignee.", ref)


def _rgpd_art14(p: ProfilOrganisme) -> Decision:
    """Article 14 : information due en cas de collecte indirecte."""
    ref = "RGPD art. 14 (vs art. 13)"
    if p.collecte_indirecte:
        return Decision(Verdict.APPLICABLE, "Collecte indirecte aupres de tiers.", ref)
    if p.collecte_indirecte is False and p.collecte_directe:
        return Decision(
            Verdict.EXEMPTE,
            "Collecte exclusivement directe : l'obligation d'information releve de "
            "l'article 13, non de l'article 14.",
            ref,
        )
    return Decision(Verdict.A_VERIFIER, "Source de collecte non renseignee.", ref)


# --------------------------------------------------------------------------
# Regles NIS2
# --------------------------------------------------------------------------

def _nis2_entite(p: ProfilOrganisme) -> Decision:
    """Obligations generales pesant sur toute entite essentielle ou
    importante (NIS2, art. 2 et 3). Le statut suffit a trancher : ces
    articles ne visent aucun sous-ensemble plus etroit."""
    ref = "NIS2, art. 2 et 3"
    if p.entite_nis2 is None:
        return Decision(Verdict.A_VERIFIER, "Statut NIS2 non renseigne.", ref)
    if p.entite_nis2 == "non_concernee":
        return Decision(
            Verdict.EXEMPTE,
            "Organisation ni entite essentielle ni entite importante au sens de NIS2.",
            ref,
        )
    return Decision(
        Verdict.APPLICABLE,
        f"Entite {p.entite_nis2} au sens de NIS2 : obligation applicable.",
        ref,
    )


def _nis2_dns(p: ProfilOrganisme) -> Decision:
    """Articles 27 et 28 : ne visent pas toute entite essentielle/importante
    mais specifiquement les fournisseurs de services DNS, les registres de
    noms de domaine de premier niveau et les entites d'enregistrement de
    noms de domaine (voir correction 1 en tete de module). Le statut
    essentielle/importante seul ne suffit donc pas a conclure."""
    ref = "NIS2, art. 27 et 28 (fournisseurs DNS et registres de noms de domaine)"
    if p.entite_nis2 == "non_concernee":
        return Decision(
            Verdict.EXEMPTE,
            "Organisation hors champ NIS2 : ne peut relever du role specifique vise par cet article.",
            ref,
        )
    return Decision(
        Verdict.A_VERIFIER,
        "Vise specifiquement les fournisseurs de services DNS et registres de noms de "
        "domaine, pas toute entite essentielle/importante : role a verifier.",
        ref,
    )


# --------------------------------------------------------------------------
# Regles DORA
# --------------------------------------------------------------------------

def _dora_entite_financiere(p: ProfilOrganisme) -> Decision:
    """Obligations generales pesant sur toute entite financiere (DORA, art. 2)."""
    ref = "DORA, art. 2"
    if p.entite_financiere_dora is None:
        return Decision(Verdict.A_VERIFIER, "Statut d'entite financiere DORA non renseigne.", ref)
    if p.entite_financiere_dora is False:
        return Decision(
            Verdict.EXEMPTE,
            "Organisation non consideree comme une entite financiere au sens de DORA.",
            ref,
        )
    return Decision(Verdict.APPLICABLE, "Entite financiere au sens de DORA : obligation applicable.", ref)


def _dora_paiement(p: ProfilOrganisme) -> Decision:
    """Article 23 : ne vise que les etablissements de credit, etablissements
    de paiement, prestataires de services d'information sur les comptes et
    etablissements de monnaie electronique -- pas toute entite financiere
    (voir correction 2 en tete de module)."""
    ref = "DORA, art. 23 (etablissements de credit, de paiement et assimiles)"
    if p.entite_financiere_dora is False:
        return Decision(
            Verdict.EXEMPTE,
            "Organisation non entite financiere : ne peut relever du role specifique vise par cet article.",
            ref,
        )
    return Decision(
        Verdict.A_VERIFIER,
        "Vise specifiquement les etablissements de credit, de paiement et assimiles, "
        "pas toute entite financiere : role a verifier.",
        ref,
    )


def _dora_institutionnel(p: ProfilOrganisme) -> Decision:
    """Articles 15, 20 et 21 : obligations des AES (autorites europeennes de
    surveillance), jamais de l'entite financiere elle-meme (voir
    correction 3 en tete de module). Toujours exempte."""
    return Decision(
        Verdict.EXEMPTE,
        "Obligation des autorites europeennes de surveillance (AES), pas de l'entite "
        "financiere elle-meme.",
        "DORA (article institutionnel, hors obligations de l'entite financiere)",
    )


# --------------------------------------------------------------------------
# Regles AI Act
# --------------------------------------------------------------------------

def _ai_act_jamais_exempte(p: ProfilOrganisme) -> Decision:
    """Article 5 : pratiques interdites, s'applique a tout operateur
    independamment de son role ou du niveau de risque du systeme. Jamais
    exempte."""
    return Decision(
        Verdict.APPLICABLE,
        "Pratiques interdites en matiere d'IA : s'applique a tout operateur, sans exception.",
        "AI Act, art. 5",
    )


def _ai_act_transparence(p: ProfilOrganisme) -> Decision:
    """Article 50 : obligations de transparence, independantes du niveau de
    risque -- s'appliquent des lors que l'organisation fournit ou deploie un
    systeme d'IA, quel qu'il soit."""
    ref = "AI Act, art. 50"
    if p.ia_utilisee is None:
        return Decision(Verdict.A_VERIFIER, "Usage de systemes d'IA non renseigne.", ref)
    if p.ia_utilisee is False:
        return Decision(
            Verdict.EXEMPTE, "Organisation ne fournissant ni ne deployant aucun systeme d'IA.", ref
        )
    return Decision(
        Verdict.APPLICABLE,
        "Organisation fournissant ou deployant un systeme d'IA : obligations de "
        "transparence applicables.",
        ref,
    )


def _ai_act_fournisseur(p: ProfilOrganisme) -> Decision:
    """Exigences applicables aux systemes d'IA a haut risque et obligations
    du fournisseur (AI Act, art. 6 et 16)."""
    ref = "AI Act, art. 6 et 16"
    if p.ia_fournisseur_haut_risque is None:
        return Decision(
            Verdict.A_VERIFIER, "Statut de fournisseur de systeme d'IA a haut risque non renseigne.", ref
        )
    if p.ia_fournisseur_haut_risque is False:
        return Decision(
            Verdict.EXEMPTE, "Organisation ne fournissant aucun systeme d'IA a haut risque.", ref
        )
    return Decision(
        Verdict.APPLICABLE, "Fournisseur d'un systeme d'IA a haut risque : obligation applicable.", ref
    )


def _ai_act_deployeur(p: ProfilOrganisme) -> Decision:
    """Obligations generales du deployeur d'un systeme d'IA a haut risque
    (AI Act, art. 26)."""
    ref = "AI Act, art. 26"
    if p.ia_deployeur_haut_risque is None:
        return Decision(
            Verdict.A_VERIFIER, "Statut de deployeur de systeme d'IA a haut risque non renseigne.", ref
        )
    if p.ia_deployeur_haut_risque is False:
        return Decision(
            Verdict.EXEMPTE, "Organisation ne deployant aucun systeme d'IA a haut risque.", ref
        )
    return Decision(
        Verdict.APPLICABLE, "Deployeur d'un systeme d'IA a haut risque : obligation applicable.", ref
    )


def _ai_act_deployeur_restreint(p: ProfilOrganisme) -> Decision:
    """Articles 27 et 86 : ne visent qu'un sous-ensemble des deployeurs de
    systemes a haut risque (voir correction 4 en tete de module). Etre
    deployeur d'un systeme a haut risque ne suffit donc pas a conclure ;
    seule l'absence de tout deploiement a haut risque exempte avec
    certitude."""
    ref = "AI Act, art. 27 et 86 (sous-ensemble des deployeurs a haut risque)"
    if p.ia_deployeur_haut_risque is False:
        return Decision(
            Verdict.EXEMPTE,
            "Organisation ne deployant aucun systeme d'IA a haut risque : ne peut relever "
            "du sous-ensemble vise.",
            ref,
        )
    return Decision(
        Verdict.A_VERIFIER,
        "Vise un sous-ensemble specifique des deployeurs de systemes a haut risque : "
        "perimetre exact a verifier.",
        ref,
    )


# Clees sur (code du referentiel, numero d'article). Toute exigence absente de
# cette table est APPLICABLE : le filtre ne peut pas ecarter ce qu'il ne connait
# pas, et un referentiel non couvert (NIS2, CSRD) passe integralement.
REGLES: dict[tuple[str, int], Callable[[ProfilOrganisme], Decision]] = {
    ("rgpd", 13): _rgpd_art13,
    ("rgpd", 14): _rgpd_art14,
    ("rgpd", 30): _rgpd_art30,
    ("rgpd", 37): _rgpd_art37,

    ("nis2", 20): _nis2_entite,
    ("nis2", 21): _nis2_entite,
    ("nis2", 23): _nis2_entite,
    ("nis2", 24): _nis2_entite,
    ("nis2", 27): _nis2_dns,
    ("nis2", 28): _nis2_dns,
    ("nis2", 29): _nis2_entite,
    ("nis2", 30): _nis2_entite,

    ("dora", 5): _dora_entite_financiere,
    ("dora", 6): _dora_entite_financiere,
    ("dora", 7): _dora_entite_financiere,
    ("dora", 8): _dora_entite_financiere,
    ("dora", 9): _dora_entite_financiere,
    ("dora", 10): _dora_entite_financiere,
    ("dora", 11): _dora_entite_financiere,
    ("dora", 12): _dora_entite_financiere,
    ("dora", 13): _dora_entite_financiere,
    ("dora", 14): _dora_entite_financiere,
    ("dora", 15): _dora_institutionnel,
    ("dora", 16): _dora_entite_financiere,
    ("dora", 17): _dora_entite_financiere,
    ("dora", 18): _dora_entite_financiere,
    ("dora", 19): _dora_entite_financiere,
    ("dora", 20): _dora_institutionnel,
    ("dora", 21): _dora_institutionnel,
    ("dora", 22): _dora_entite_financiere,
    ("dora", 23): _dora_paiement,
    ("dora", 24): _dora_entite_financiere,
    ("dora", 25): _dora_entite_financiere,
    ("dora", 26): _dora_entite_financiere,
    ("dora", 27): _dora_entite_financiere,
    ("dora", 28): _dora_entite_financiere,
    ("dora", 29): _dora_entite_financiere,
    ("dora", 30): _dora_entite_financiere,

    ("ai_act", 5): _ai_act_jamais_exempte,
    ("ai_act", 8): _ai_act_fournisseur,
    ("ai_act", 9): _ai_act_fournisseur,
    ("ai_act", 10): _ai_act_fournisseur,
    ("ai_act", 11): _ai_act_fournisseur,
    ("ai_act", 12): _ai_act_fournisseur,
    ("ai_act", 13): _ai_act_fournisseur,
    ("ai_act", 14): _ai_act_fournisseur,
    ("ai_act", 15): _ai_act_fournisseur,
    ("ai_act", 16): _ai_act_fournisseur,
    ("ai_act", 17): _ai_act_fournisseur,
    ("ai_act", 18): _ai_act_fournisseur,
    ("ai_act", 19): _ai_act_fournisseur,
    ("ai_act", 20): _ai_act_fournisseur,
    ("ai_act", 21): _ai_act_fournisseur,
    ("ai_act", 22): _ai_act_fournisseur,
    # 23, 24 (importateurs, distributeurs) : aucune regle, voir correction 5
    # en tete de module -- role distinct de celui du fournisseur, pas de
    # champ de profil dedie. Reste APPLICABLE par defaut.
    ("ai_act", 25): _ai_act_fournisseur,
    ("ai_act", 26): _ai_act_deployeur,
    ("ai_act", 27): _ai_act_deployeur_restreint,
    ("ai_act", 47): _ai_act_fournisseur,
    ("ai_act", 48): _ai_act_fournisseur,
    ("ai_act", 49): _ai_act_fournisseur,
    ("ai_act", 50): _ai_act_transparence,
    ("ai_act", 72): _ai_act_fournisseur,
    ("ai_act", 73): _ai_act_fournisseur,
    ("ai_act", 86): _ai_act_deployeur_restreint,
}

_APPLICABLE_PAR_DEFAUT = Decision(
    Verdict.APPLICABLE,
    "Exigence sans condition d'applicabilite liee au profil de l'organisme.",
    "",
)


# --------------------------------------------------------------------------
# API publique
# --------------------------------------------------------------------------

def evaluer(framework: str, numero_article: int | None, profil: ProfilOrganisme) -> Decision:
    """Evalue l'applicabilite d'un article au profil donne."""
    if numero_article is None:
        return _APPLICABLE_PAR_DEFAUT
    regle = REGLES.get((framework.strip().lower(), numero_article))
    return regle(profil) if regle else _APPLICABLE_PAR_DEFAUT


def filtrer_exigences(
    exigences: Iterable[ExigenceLike],
    framework: str,
    profil: ProfilOrganisme,
    numero_de: Callable[[str], int | None],
) -> tuple[list[ExigenceLike], list[tuple[ExigenceLike, Decision]]]:
    """
    Separe les exigences a evaluer de celles exemptees par le profil.

    `numero_de` est injectee pour reutiliser `_article_number_of` du moteur
    d'audit plutot que d'entretenir deux logiques de parsing divergentes.

    Retourne (a_evaluer, exemptees). Les exemptees portent leur Decision : elles
    doivent etre inscrites au rapport comme non applicables et justifiees, jamais
    disparaitre silencieusement.
    """
    a_evaluer: list[ExigenceLike] = []
    exemptees: list[tuple[ExigenceLike, Decision]] = []

    for exigence in exigences:
        decision = evaluer(framework, numero_de(exigence.reference), profil)
        if decision.conserver:
            a_evaluer.append(exigence)
        else:
            exemptees.append((exigence, decision))

    return a_evaluer, exemptees


def referentiel_hors_champ(framework: str, profil: ProfilOrganisme) -> bool:
    """Le referentiel choisi ne s'applique-t-il certainement pas du tout a
    cette organisation ? Vrai seulement si TOUS ses articles auditables
    resolvent a EXEMPTE pour ce profil -- pas simplement si aucun n'est
    APPLICABLE (un profil non renseigne donne A_VERIFIER partout, jamais
    EXEMPTE, donc cette fonction renvoie toujours False pour un profil vide :
    c'est le comportement voulu, l'absence d'information n'emet jamais cet
    avertissement).

    Sert uniquement a avertir a la creation d'une campagne (voir
    POST /orgs/{org_id}/audits) ; ne bloque jamais la creation.
    """
    from app.ingestion.scoping import WHITELISTS

    auditables = WHITELISTS.get(framework.strip().lower())
    if not auditables:
        return False
    numeros_auditables, _ = auditables
    if not numeros_auditables:
        return False
    return all(
        evaluer(framework, numero, profil).verdict is Verdict.EXEMPTE
        for numero in numeros_auditables
    )


def _entier(valeur) -> int | None:
    """N'accepte qu'un entier reel.

    Le typage est verifie plutot que suppose : un doublure de test ou un objet
    de mapping paresseux renverrait un attribut non nul mais denue de sens, que
    le filtre interpreterait comme un profil renseigne. Une valeur douteuse est
    ramenee a None, donc a A_VERIFIER.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        return None
    return valeur


def _booleen(valeur) -> bool | None:
    if not isinstance(valeur, bool):
        return None
    return valeur


_ENTITE_NIS2_VALEURS = {"essentielle", "importante", "non_concernee"}


def _entite_nis2(valeur) -> str | None:
    """N'accepte que les trois valeurs reconnues. Une valeur inattendue
    (colonne corrompue, saisie API hors schema) est ramenee a None, donc a
    A_VERIFIER -- jamais interpretee comme une exemption."""
    if not isinstance(valeur, str) or valeur not in _ENTITE_NIS2_VALEURS:
        return None
    return valeur


def depuis_organisation(organisation) -> ProfilOrganisme:
    """
    Adaptateur vers le modele Organization.

    Deux champs sont deja portes par le modele : `headcount` alimente l'effectif,
    qui suffit a trancher l'article 30 des lors que les conditions de l'alinea 5
    sont renseignees. Les autres attendent une migration ; tant qu'ils sont
    absents, `getattr` renvoie None et le filtre repond A_VERIFIER, ce qui laisse
    le comportement inchange.

    Regle imperative : ne jamais convertir une absence de donnee en False, sans
    quoi le filtre exempterait a tort et introduirait des faux negatifs.
    """
    if organisation is None:
        return ProfilOrganisme()

    return ProfilOrganisme(
        effectif=_entier(getattr(organisation, "headcount", None)),
        organisme_public=_booleen(getattr(organisation, "organisme_public", None)),
        donnees_sensibles_art9=_booleen(getattr(organisation, "donnees_sensibles", None)),
        donnees_penales_art10=_booleen(getattr(organisation, "donnees_penales", None)),
        activite_de_base_traitement=_booleen(getattr(organisation, "activite_de_base_traitement", None)),
        suivi_regulier_systematique=_booleen(getattr(organisation, "suivi_regulier_systematique", None)),
        grande_echelle=_booleen(getattr(organisation, "grande_echelle", None)),
        professionnel_liberal_isole=_booleen(getattr(organisation, "professionnel_liberal_isole", None)),
        traitement_occasionnel=_booleen(getattr(organisation, "traitement_occasionnel", None)),
        risque_droits_libertes=_booleen(getattr(organisation, "risque_droits_libertes", None)),
        collecte_directe=_booleen(getattr(organisation, "collecte_directe", None)),
        collecte_indirecte=_booleen(getattr(organisation, "collecte_indirecte", None)),
        entite_nis2=_entite_nis2(getattr(organisation, "entite_nis2", None)),
        entite_financiere_dora=_booleen(getattr(organisation, "entite_financiere_dora", None)),
        ia_fournisseur_haut_risque=_booleen(getattr(organisation, "ia_fournisseur_haut_risque", None)),
        ia_deployeur_haut_risque=_booleen(getattr(organisation, "ia_deployeur_haut_risque", None)),
        ia_utilisee=_booleen(getattr(organisation, "ia_utilisee", None)),
    )