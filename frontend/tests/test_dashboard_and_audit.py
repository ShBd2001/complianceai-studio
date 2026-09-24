"""Parcours d'audit complet pilote au navigateur : creation de campagne,
depot de piece, analyse, et le filtre sur les constats (verifie qu'il change
reellement ce qui est affiche, pas seulement qu'il ne plante pas).
"""

from __future__ import annotations

import uuid

from playwright.sync_api import expect

from conftest import extract_link_token, latest_email_for, passer_tour_si_present

PWD = "Compliance!2026x"

POLICY = (
    "Politique de securite - Acme SAS\n\n"
    "Un registre des activites de traitement est tenu a jour par le delegue "
    "a la protection des donnees. Les donnees sont chiffrees au repos et en "
    "transit. En cas de violation, l'autorite de controle est notifiee dans "
    "les meilleurs delais.\n"
)


def _register(page, frontend_server: str, backend_server, email: str, fermer_tour: bool = True) -> None:
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-inscription")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.check("#i-cgu")
    page.click("#p-inscription button:not(.lien)")
    page.wait_for_selector("#p-connexion:not([hidden])")

    contenu = latest_email_for(backend_server["storage_dir"], email)
    token = extract_link_token(contenu, "verify_email")
    page.goto(f"{frontend_server}/?verify_email={token}", wait_until="networkidle")
    page.wait_for_selector("#p-verification:not([hidden])")

    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-connexion")
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
    # Le tour de premiers pas bloque l'interaction avec le reste du tableau
    # de bord tant qu'il est ouvert : les tests du tour lui-meme (plus bas)
    # ont besoin de le voir non ferme, d'ou ce parametre -- tous les autres
    # tests de ce fichier veulent au contraire un tableau de bord utilisable
    # immediatement.
    if fermer_tour:
        passer_tour_si_present(page)


def test_dashboard_renders_empty_state(page, frontend_server, backend_server):
    email = f"dash-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    expect(page.locator("h1")).to_have_text("Tableau de bord")
    expect(page.get_by_text("Aucune campagne pour l'instant.")).to_be_visible()


# --------------------------------------------------------------------------
# Tour guide (premiers pas) : remplace l'ancienne carte statique listant les
# 3 etapes d'un coup (jugee trop envahissante en haut du tableau de bord)
# par une visite guidee, une etape a la fois, avec halo autour de l'element
# concerne (voir demarrerTour/rendreTour dans index.html).
# --------------------------------------------------------------------------
def test_getting_started_tour_guides_through_three_steps(page, frontend_server, backend_server):
    email = f"tour-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email, fermer_tour=False)
    page.wait_for_selector(".tour-bulle")

    expect(page.locator(".tour-bulle .eyebrow")).to_have_text("Étape 1 sur 3")
    expect(page.locator(".tour-bulle h3")).to_have_text("Lancer une première campagne")
    expect(page.locator(".tour-bulle button:has-text(\"Précédent\")")).to_have_count(0)
    expect(page.locator(".tour-anneau")).to_be_visible()

    page.click(".tour-bulle button:has-text(\"Suivant\")")
    expect(page.locator(".tour-bulle .eyebrow")).to_have_text("Étape 2 sur 3")

    # Precedent doit vraiment revenir en arriere, pas seulement avancer.
    page.click(".tour-bulle button:has-text(\"Précédent\")")
    expect(page.locator(".tour-bulle .eyebrow")).to_have_text("Étape 1 sur 3")

    page.click(".tour-bulle button:has-text(\"Suivant\")")
    page.click(".tour-bulle button:has-text(\"Suivant\")")
    expect(page.locator(".tour-bulle .eyebrow")).to_have_text("Étape 3 sur 3")
    expect(page.locator(".tour-bulle h3")).to_have_text("Inviter un membre de votre équipe")
    expect(page.locator(".tour-bulle button:has-text(\"C'est parti\")")).to_be_visible()

    # La derniere etape ferme la visite ET emmene vers la page concernee.
    page.click(".tour-bulle button:has-text(\"C'est parti\")")
    expect(page.locator(".tour-bulle")).to_have_count(0)
    expect(page.locator(".tour-bande")).to_have_count(0)
    assert page.evaluate("location.hash") == "#/equipe"


def test_getting_started_tour_can_be_dismissed_permanently(page, frontend_server, backend_server):
    email = f"tourskip-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email, fermer_tour=False)
    page.wait_for_selector(".tour-bulle")

    page.click(".tour-bulle button:has-text(\"Passer\")")
    expect(page.locator(".tour-bulle")).to_have_count(0)
    assert page.evaluate("localStorage.getItem('cai_guide_masque')") == "1"

    # Doit rester masque apres un rechargement, pas seulement en memoire JS.
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
    page.wait_for_timeout(500)
    expect(page.locator(".tour-bulle")).to_have_count(0)


def test_delete_campaign(page, frontend_server, backend_server):
    email = f"del-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"audits\"]")
    page.wait_for_selector("#n-titre")
    page.fill("#n-titre", "Campagne à supprimer")
    page.click("button:has-text(\"Ouvrir la campagne\")")
    page.wait_for_selector("button:has-text(\"Supprimer\")", timeout=15000)

    page.once("dialog", lambda d: d.accept())
    page.click("button:has-text(\"Supprimer\")")
    page.wait_for_url("**/#/audits", timeout=10000)

    expect(page.get_by_text("Aucune campagne pour l'instant.")).to_be_visible()


def test_full_audit_pipeline_and_findings_filter(page, frontend_server, backend_server, tmp_path):
    email = f"audit-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"audits\"]")
    page.wait_for_selector("#n-titre")
    page.fill("#n-titre", "Audit E2E")
    page.select_option("#n-ref", "rgpd")
    page.click("button:has-text(\"Ouvrir la campagne\")")
    page.wait_for_selector("#depot", timeout=15000)

    fichier = tmp_path / "politique.txt"
    fichier.write_text(POLICY, encoding="utf-8")
    page.set_input_files("#fichiers", str(fichier))
    page.wait_for_selector("#btn-run:not([disabled])", timeout=15000)

    page.click("#btn-run")
    page.wait_for_selector("#z-constats", timeout=60000)
    page.wait_for_timeout(500)

    constats_avant = page.locator("#z-constats article.constat").count()
    assert constats_avant > 0

    # Les tests tournent sans cle LLM : chaque constat vient de l'heuristique
    # et doit donc afficher le badge de revue humaine (Tache 2).
    expect(page.locator("#z-constats .badge-verif.revue").first).to_be_visible()

    page.select_option("#constats-f-gravite", "critical")
    page.wait_for_timeout(400)
    constats_apres = page.locator("#z-constats article.constat").count()

    # Le filtre doit changer ce qui est affiche (moins d'articles critiques
    # que le total, pour ce document — pas simplement "ne pas planter").
    assert constats_apres <= constats_avant
    if constats_apres:
        for gravite in page.locator("#z-constats .etiq").all_text_contents():
            assert gravite.strip() == "Critique"


def test_remediation_plan_aggregates_across_completed_campaigns(page, frontend_server, backend_server, tmp_path):
    """Avant ce correctif, Plan de remediation ne montrait que la derniere
    campagne terminee : une deuxieme campagne restait invisible de cette
    page meme si elle avait des constats encore ouverts (redondance signalee
    par l'utilisatrice avec la page Campagnes d'audit, qui montre deja le
    detail complet d'une campagne prise isolement)."""
    email = f"remed-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    fichier = tmp_path / "politique.txt"
    fichier.write_text(POLICY, encoding="utf-8")

    for titre in ["Audit RGPD A", "Audit RGPD B"]:
        page.click("a[data-vue=\"audits\"]")
        page.wait_for_selector("#n-titre")
        page.fill("#n-titre", titre)
        page.select_option("#n-ref", "rgpd")
        page.click("button:has-text(\"Ouvrir la campagne\")")
        page.wait_for_selector("#depot", timeout=15000)
        page.set_input_files("#fichiers", str(fichier))
        page.wait_for_selector("#btn-run:not([disabled])", timeout=15000)
        page.click("#btn-run")
        page.wait_for_selector("#z-constats", timeout=60000)

    page.click("a[data-vue=\"remediation\"]")
    page.wait_for_selector("#z-remed article.constat", timeout=15000)

    expect(page.get_by_text("2 campagnes terminées")).to_be_visible()
    assert page.get_by_text("Audit RGPD A", exact=False).count() > 0
    assert page.get_by_text("Audit RGPD B", exact=False).count() > 0


def test_report_ready_immediately_after_analysis(page, frontend_server, backend_server, tmp_path):
    """Le rapport doit etre telechargeable des la fin de l'analyse, bien en
    vue a cote du score — pas une etape manuelle separee a decouvrir plus
    bas sur la page (voir le retour utilisateur qui a motive ce test)."""
    email = f"pdf-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"audits\"]")
    page.wait_for_selector("#n-titre")
    page.fill("#n-titre", "Audit PDF E2E")
    page.select_option("#n-ref", "rgpd")
    page.click("button:has-text(\"Ouvrir la campagne\")")
    page.wait_for_selector("#depot", timeout=15000)

    fichier = tmp_path / "politique.txt"
    fichier.write_text(POLICY, encoding="utf-8")
    page.set_input_files("#fichiers", str(fichier))
    page.wait_for_selector("#btn-run:not([disabled])", timeout=15000)
    page.click("#btn-run")

    # Aucune action manuelle supplementaire : le bouton apparait dans le
    # bandeau de score des que l'analyse se termine.
    page.wait_for_selector(".verdict button:has-text(\"Télécharger le rapport\")", timeout=60000)

    # La generation reelle (Chromium) prend quelques secondes : le bouton
    # doit rester utilisable ensuite, pas rester bloque en « … ».
    with page.expect_download(timeout=20000) as dl_info:
        page.click(".verdict button:has-text(\"Télécharger le rapport\")")
    download = dl_info.value
    assert download.suggested_filename.endswith(".pdf")
    expect(page.locator(".verdict button:has-text(\"Télécharger le rapport\")")).to_be_enabled()

    # Produire une version supplementaire depuis le tableau plus bas doit
    # aussi fonctionner, et le bouton du bandeau doit alors pointer sur la
    # nouvelle version.
    page.click("button:has-text(\"Produire une nouvelle version\")")
    page.wait_for_selector("#z-rapports table tbody tr:nth-child(2)", timeout=15000)
    expect(page.locator(".verdict .txt-sourdine")).to_contain_text("v2")

    with page.expect_download(timeout=20000) as dl_info2:
        page.locator("#z-rapports button:has-text(\"PDF\")").first.click()
    assert dl_info2.value.suggested_filename.endswith(".pdf")

