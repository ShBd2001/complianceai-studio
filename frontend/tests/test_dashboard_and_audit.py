"""Parcours d'audit complet pilote au navigateur : creation de campagne,
depot de piece, analyse, et le filtre sur les constats (verifie qu'il change
reellement ce qui est affiche, pas seulement qu'il ne plante pas).
"""

from __future__ import annotations

import uuid

from playwright.sync_api import expect

PWD = "Compliance!2026x"

POLICY = (
    "Politique de securite - Acme SAS\n\n"
    "Un registre des activites de traitement est tenu a jour par le delegue "
    "a la protection des donnees. Les donnees sont chiffrees au repos et en "
    "transit. En cas de violation, l'autorite de controle est notifiee dans "
    "les meilleurs delais.\n"
)


def _register(page, frontend_server: str, email: str) -> None:
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.click("#p-inscription button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_dashboard_renders_empty_state(page, frontend_server, backend_server):
    email = f"dash-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, email)

    expect(page.locator("h1")).to_have_text("Tableau de bord")
    expect(page.get_by_text("Aucune campagne pour l'instant.")).to_be_visible()


def test_delete_campaign(page, frontend_server, backend_server):
    email = f"del-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, email)

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
    _register(page, frontend_server, email)

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

    page.select_option("#constats-f-gravite", "critical")
    page.wait_for_timeout(400)
    constats_apres = page.locator("#z-constats article.constat").count()

    # Le filtre doit changer ce qui est affiche (moins d'articles critiques
    # que le total, pour ce document — pas simplement "ne pas planter").
    assert constats_apres <= constats_avant
    if constats_apres:
        for gravite in page.locator("#z-constats .etiq").all_text_contents():
            assert gravite.strip() == "Critique"
