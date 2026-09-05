"""Perimetre auditable : quelles exigences sont confrontees aux documents.

Ces tests protegent un choix metier, pas une implementation. Auditer une
entreprise contre un article qui s'adresse a la CNIL produirait des constats
faux, et c'est le genre de defaut qu'un jury releve immediatement.
"""

import pytest

from app.ingestion.scoping import Audience, classify


@pytest.mark.parametrize(
    "reference,body",
    [
        ("Article 5", "Les donnees a caractere personnel doivent etre traitees de maniere licite."),
        ("Article 30", "Chaque responsable du traitement tient un registre des activites."),
        ("Article 32", "Le responsable du traitement met en oeuvre les mesures techniques."),
        ("Article 33", "Le responsable du traitement notifie la violation a l'autorite."),
        ("Article 35", "Le responsable du traitement effectue une analyse d'impact."),
        ("Article 37", "Le responsable du traitement designe un delegue a la protection."),
        ("Article 44", "Un transfert vers un pays tiers ne peut avoir lieu que si..."),
    ],
)
def test_rgpd_obligations_are_auditable(reference, body):
    scope = classify("rgpd", reference, body)
    assert scope.auditable is True
    assert scope.audience is Audience.ENTITY


@pytest.mark.parametrize(
    "reference,body",
    [
        ("Article 1", "Le present reglement etablit des regles."),
        ("Article 4", "Aux fins du present reglement, on entend par..."),
        ("Article 51", "Chaque Etat membre prevoit une autorite de controle independante."),
        ("Article 68", "Le comite europeen de la protection des donnees est institue."),
        ("Article 83", "Chaque autorite de controle veille a ce que les amendes soient effectives."),
        ("Article 99", "Le present reglement entre en vigueur le vingtieme jour."),
    ],
)
def test_rgpd_non_obligations_are_excluded(reference, body):
    assert classify("rgpd", reference, body).auditable is False


def test_rgpd_perimeter_size():
    """Le RGPD compte 99 articles, dont 45 opposables a une organisation."""
    auditable = [
        n for n in range(1, 100)
        if classify("rgpd", f"Article {n}", "texte").auditable
    ]
    assert len(auditable) == 45
    # Les deux articles les plus audites en pratique doivent en faire partie.
    assert 30 in auditable
    assert 32 in auditable


def test_nis2_entity_obligations():
    assert classify("nis2", "Article 21", "mesures de gestion des risques").auditable is True
    assert classify("nis2", "Article 23", "obligations de notification").auditable is True
    # La designation d'une autorite nationale ne concerne pas l'entite auditee.
    assert classify("nis2", "Article 8", "Chaque Etat membre designe").auditable is False


def test_dora_entity_obligations():
    assert classify("dora", "Article 6", "cadre de gestion du risque lie aux TIC").auditable is True
    assert classify("dora", "Article 24", "tests de resilience operationnelle numerique").auditable is True
    assert classify("dora", "Article 30", "principales dispositions contractuelles").auditable is True
    # A partir de l'article 31, c'est le regime de supervision des
    # prestataires tiers critiques par les AES, pas une obligation de
    # l'entite financiere auditee.
    assert classify("dora", "Article 35", "pouvoirs du superviseur principal").auditable is False
    assert classify("dora", "Article 2", "champ d'application").auditable is False


def test_dora_perimeter_size():
    """26 articles sur 64 imposent une obligation directe a l'entite financiere."""
    auditable = [
        n for n in range(1, 65)
        if classify("dora", f"Article {n}", "texte").auditable
    ]
    assert len(auditable) == 26
    assert 6 in auditable
    assert 30 in auditable
    assert 31 not in auditable


def test_ai_act_entity_obligations():
    assert classify("ai_act", "Article 9", "systeme de gestion des risques").auditable is True
    assert classify("ai_act", "Article 10", "donnees et gouvernance des donnees").auditable is True
    assert classify("ai_act", "Article 11", "documentation technique").auditable is True
    assert classify("ai_act", "Article 5", "pratiques interdites en matiere d'IA").auditable is True
    # Le regime des organismes notifies (evaluation de la conformite par des
    # tiers accredites) est institutionnel, pas une obligation du fournisseur.
    assert classify("ai_act", "Article 33", "filiales des organismes notifies").auditable is False
    assert classify("ai_act", "Article 58", "bacs a sable reglementaires").auditable is False


def test_ai_act_perimeter_size():
    """28 articles sur 113 imposent une obligation directe au fournisseur/deployeur."""
    auditable = [
        n for n in range(1, 114)
        if classify("ai_act", f"Article {n}", "texte").auditable
    ]
    assert len(auditable) == 28
    assert 9 in auditable
    assert 73 in auditable


def test_csrd_inserted_articles_carry_the_obligations():
    assert classify("csrd", "Article 29 quater", "La Commission adopte").auditable is True
    assert classify("csrd", "Article 40 bis", "Les Etats membres exigent").auditable is True
    assert classify("csrd", "Article 5", "Transposition").auditable is False


def test_unknown_framework_falls_back_to_markers():
    """Sans liste blanche, on tranche sur le destinataire dominant du texte."""
    entity = classify(
        "inconnu", "Article 12",
        "Le responsable du traitement met en oeuvre des mesures. "
        "Le responsable du traitement documente ces mesures.",
    )
    assert entity.auditable is True

    state = classify(
        "inconnu", "Article 12",
        "Les Etats membres veillent. Les Etats membres notifient a la Commission.",
    )
    assert state.auditable is False
    assert state.audience is Audience.MEMBER_STATE


# --------------------------------------------------------------------------
# Dependances entre exigences
# --------------------------------------------------------------------------
def test_dpo_articles_depend_on_designation():
    """38 et 39 decoulent de 37 : sans delegue obligatoire, ils sont sans objet."""
    from app.ingestion.scoping import dependency_of

    assert dependency_of("rgpd", "Article 38") == 37
    assert dependency_of("rgpd", "Article 39") == 37
    assert dependency_of("rgpd", "Article 37") is None


def test_transfer_articles_depend_on_the_general_principle():
    from app.ingestion.scoping import dependency_of

    for article in (45, 46, 47, 48, 49):
        assert dependency_of("rgpd", f"Article {article}") == 44


def test_independent_articles_have_no_dependency():
    from app.ingestion.scoping import dependency_of

    for article in (5, 30, 32, 33):
        assert dependency_of("rgpd", f"Article {article}") is None


def test_propagation_excludes_dependent_requirements():
    """Le cas reel : 37 hors perimetre, 39 en non-conformite majeure.

    Le rapport se contredisait — aucun delegue n'est requis, mais ses missions
    ne sont pas documentees. La propagation rend les deux verdicts coherents.
    """
    from app.services.audit_engine import NOT_APPLICABLE, _propagate_dependencies

    class Req:
        def __init__(self, reference: str) -> None:
            self.reference = reference

    requirements = [Req("Article 37"), Req("Article 39"), Req("Article 30")]
    verdicts = [
        {"conforme": "non_applicable", "severite": "info",
         "constat": "Pas de traitement a grande echelle."},
        {"conforme": "non", "severite": "major",
         "constat": "Les missions du delegue ne sont pas documentees.",
         "recommandation": "Designer un delegue."},
        {"conforme": "non", "severite": "major",
         "constat": "Aucun registre.", "recommandation": "Tenir un registre."},
    ]

    reclassified = _propagate_dependencies("rgpd", requirements, verdicts)

    assert reclassified == 1
    assert verdicts[1]["conforme"] == NOT_APPLICABLE
    assert verdicts[1]["recommandation"] is None
    assert "article 37" in verdicts[1]["constat"]
    # L'article 30 est independant : il reste une non-conformite.
    assert verdicts[2]["conforme"] == "non"
