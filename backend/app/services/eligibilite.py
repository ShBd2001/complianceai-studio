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
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Protocol, Sequence


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


# Clees sur (code du referentiel, numero d'article). Toute exigence absente de
# cette table est APPLICABLE : le filtre ne peut pas ecarter ce qu'il ne connait
# pas, et un referentiel non couvert (NIS2, CSRD) passe integralement.
REGLES: dict[tuple[str, int], Callable[[ProfilOrganisme], Decision]] = {
    ("rgpd", 13): _rgpd_art13,
    ("rgpd", 14): _rgpd_art14,
    ("rgpd", 30): _rgpd_art30,
    ("rgpd", 37): _rgpd_art37,
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
    )