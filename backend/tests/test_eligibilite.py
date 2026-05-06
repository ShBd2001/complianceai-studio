"""
Tests du filtre d'eligibilite.

Les cas sont cales sur les documents du corpus de validation qui produisaient
les faux positifs art.30 / art.37 / art.13, plus les cas de non-regression qui
garantissent qu'aucun faux negatif n'est introduit.
"""

import re
from dataclasses import dataclass

import pytest

from app.services.eligibilite import (
    ProfilOrganisme,
    Verdict,
    depuis_organisation,
    evaluer,
    filtrer_exigences,
)


def numero_de(reference: str) -> int | None:
    """Reproduit `_article_number_of` du moteur d'audit."""
    match = re.search(r"Article\s+(\d+)", reference, re.IGNORECASE)
    return int(match.group(1)) if match else None


@dataclass
class ExigenceFactice:
    reference: str


# --------------------------------------------------------------------------
# Article 30 - registre des traitements
# --------------------------------------------------------------------------

def test_art30_grande_entreprise_reste_applicable():
    """01_grande_pme_conforme : au-dela de 250 salaries, aucune dispense."""
    assert evaluer("rgpd", 30, ProfilOrganisme(effectif=340)).verdict is Verdict.APPLICABLE


def test_art30_artisan_occasionnel_exempte():
    """04_artisan_hors_perimetre : le cas type de la dispense."""
    profil = ProfilOrganisme(
        effectif=3,
        traitement_occasionnel=True,
        risque_droits_libertes=False,
        donnees_sensibles_art9=False,
    )
    assert evaluer("rgpd", 30, profil).verdict is Verdict.EXEMPTE


def test_art30_micro_entreprise_avec_paie_reste_applicable():
    """La paie est un traitement non occasionnel : dispense ecartee."""
    profil = ProfilOrganisme(
        effectif=4,
        traitement_occasionnel=False,
        risque_droits_libertes=False,
        donnees_sensibles_art9=False,
    )
    assert evaluer("rgpd", 30, profil).verdict is Verdict.APPLICABLE


def test_art30_petit_effectif_mais_donnees_sensibles_reste_applicable():
    """06_rh_donnees_sensibles : l'article 9 retablit l'obligation."""
    profil = ProfilOrganisme(effectif=12, donnees_sensibles_art9=True, traitement_occasionnel=True)
    assert evaluer("rgpd", 30, profil).verdict is Verdict.APPLICABLE


def test_art30_effectif_inconnu_ne_supprime_pas():
    """Garde-fou principal : l'ignorance ne produit jamais d'exemption."""
    assert evaluer("rgpd", 30, ProfilOrganisme()).verdict is Verdict.A_VERIFIER


def test_art30_profil_partiel_ne_supprime_pas():
    assert evaluer("rgpd", 30, ProfilOrganisme(effectif=8)).verdict is Verdict.A_VERIFIER


# --------------------------------------------------------------------------
# Article 37 - delegue a la protection des donnees
# --------------------------------------------------------------------------

def test_art37_cabinet_medical_isole_exempte():
    """05_cabinet_medical : considerant 91, pas de grande echelle."""
    profil = ProfilOrganisme(
        effectif=2,
        organisme_public=False,
        professionnel_liberal_isole=True,
        donnees_sensibles_art9=True,
    )
    decision = evaluer("rgpd", 37, profil)
    assert decision.verdict is Verdict.EXEMPTE
    assert "91" in decision.reference


def test_art37_organisme_public_toujours_applicable():
    profil = ProfilOrganisme(effectif=15, organisme_public=True)
    assert evaluer("rgpd", 37, profil).verdict is Verdict.APPLICABLE


def test_art37_scoring_credit_applicable():
    """12_scoring_credit : suivi regulier et systematique a grande echelle."""
    profil = ProfilOrganisme(
        organisme_public=False,
        grande_echelle=True,
        activite_de_base_traitement=True,
        suivi_regulier_systematique=True,
    )
    assert evaluer("rgpd", 37, profil).verdict is Verdict.APPLICABLE


def test_art37_grande_echelle_hors_activite_de_base_exempte():
    profil = ProfilOrganisme(
        organisme_public=False,
        grande_echelle=True,
        activite_de_base_traitement=False,
    )
    assert evaluer("rgpd", 37, profil).verdict is Verdict.EXEMPTE


def test_art37_petite_association_exempte():
    """13_association_faible_maturite."""
    profil = ProfilOrganisme(effectif=6, organisme_public=False, grande_echelle=False)
    assert evaluer("rgpd", 37, profil).verdict is Verdict.EXEMPTE


def test_art37_profil_vide_ne_supprime_pas():
    assert evaluer("rgpd", 37, ProfilOrganisme()).verdict is Verdict.A_VERIFIER


# --------------------------------------------------------------------------
# Articles 13 / 14 - information des personnes
# --------------------------------------------------------------------------

def test_art13_collecte_indirecte_bascule_vers_art14():
    """10_collecte_indirecte : l'article 13 ne s'applique pas."""
    profil = ProfilOrganisme(collecte_directe=False, collecte_indirecte=True)
    assert evaluer("rgpd", 13, profil).verdict is Verdict.EXEMPTE
    assert evaluer("rgpd", 14, profil).verdict is Verdict.APPLICABLE


def test_art13_collecte_mixte_conserve_les_deux():
    profil = ProfilOrganisme(collecte_directe=True, collecte_indirecte=True)
    assert evaluer("rgpd", 13, profil).verdict is Verdict.APPLICABLE
    assert evaluer("rgpd", 14, profil).verdict is Verdict.APPLICABLE


def test_art13_source_inconnue_ne_supprime_pas():
    assert evaluer("rgpd", 13, ProfilOrganisme()).verdict is Verdict.A_VERIFIER


# --------------------------------------------------------------------------
# Isolation entre referentiels
# --------------------------------------------------------------------------

@pytest.mark.parametrize("framework", ["nis2", "csrd"])
def test_regles_rgpd_ne_fuient_pas_sur_les_autres_referentiels(framework):
    """L'article 30 de NIS2 ou CSRD n'a rien a voir avec le registre RGPD."""
    profil = ProfilOrganisme(
        effectif=3,
        traitement_occasionnel=True,
        risque_droits_libertes=False,
        donnees_sensibles_art9=False,
    )
    assert evaluer(framework, 30, profil).verdict is Verdict.APPLICABLE
    assert evaluer(framework, 37, profil).verdict is Verdict.APPLICABLE


def test_code_framework_insensible_a_la_casse():
    profil = ProfilOrganisme(effectif=400)
    assert evaluer("RGPD", 30, profil).verdict is Verdict.APPLICABLE


# --------------------------------------------------------------------------
# Comportement d'ensemble
# --------------------------------------------------------------------------

@pytest.mark.parametrize("numero", [5, 15, 32, 33])
def test_articles_inconditionnels_jamais_filtres(numero):
    """Le filtre n'ecarte jamais une exigence qu'il ne connait pas."""
    assert evaluer("rgpd", numero, ProfilOrganisme()).verdict is Verdict.APPLICABLE


def test_reference_non_parsable_reste_applicable():
    assert evaluer("rgpd", None, ProfilOrganisme()).verdict is Verdict.APPLICABLE


def test_filtrer_exigences_separe_et_trace():
    profil = ProfilOrganisme(
        effectif=2,
        organisme_public=False,
        professionnel_liberal_isole=True,
        traitement_occasionnel=True,
        risque_droits_libertes=False,
        donnees_sensibles_art9=False,
    )
    exigences = [ExigenceFactice(r) for r in ("Article 5", "Article 30", "Article 32", "Article 37")]

    a_evaluer, exemptees = filtrer_exigences(exigences, "rgpd", profil, numero_de)

    assert [e.reference for e in a_evaluer] == ["Article 5", "Article 32"]
    assert [e.reference for e, _ in exemptees] == ["Article 30", "Article 37"]
    assert all(d.justification and d.reference for _, d in exemptees)


def test_profil_vide_ne_retire_aucune_exigence():
    """Non-regression sur le rappel : un profil vide conserve 100% du perimetre."""
    exigences = [ExigenceFactice(f"Article {n}") for n in (5, 13, 14, 30, 32, 37)]
    a_evaluer, exemptees = filtrer_exigences(exigences, "rgpd", ProfilOrganisme(), numero_de)
    assert len(a_evaluer) == len(exigences)
    assert exemptees == []


def test_organisation_absente_donne_profil_vide():
    """Un audit sans organisation liee ne doit rien exempter."""
    assert depuis_organisation(None) == ProfilOrganisme()

# --------------------------------------------------------------------------
# Adaptateur vers le modele Organization
# --------------------------------------------------------------------------

def test_adaptateur_lit_headcount():
    """`headcount` existe deja sur le modele : l'effectif est exploitable sans migration."""
    class Org:
        headcount = 340

    assert depuis_organisation(Org()).effectif == 340


def test_adaptateur_ignore_les_valeurs_non_typees():
    """Une doublure de test ne doit pas se faire passer pour un profil renseigne."""
    from unittest.mock import MagicMock

    profil = depuis_organisation(MagicMock())
    assert profil == ProfilOrganisme()


def test_adaptateur_colonnes_absentes_donne_profil_vide():
    """Avant migration, seul l'effectif est connu : le reste reste indecidable."""
    class Org:
        headcount = None

    assert depuis_organisation(Org()) == ProfilOrganisme()
