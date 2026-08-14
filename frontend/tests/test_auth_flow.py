"""Parcours d'authentification pilotes au vrai navigateur : inscription,
verification d'e-mail via le lien reellement envoye (repli fichier local),
connexion, mot de passe oublie de bout en bout.
"""

from __future__ import annotations

import re
import time
import uuid
from pathlib import Path

from playwright.sync_api import expect

PWD = "Compliance!2026x"


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@exemple.fr"


def _latest_email_for(storage_dir: Path, address: str) -> str:
    emails_dir = storage_dir / "emails"
    deadline = time.monotonic() + 5
    fichiers: list[Path] = []
    while time.monotonic() < deadline:
        if emails_dir.exists():
            fichiers = sorted(p for p in emails_dir.glob("*.txt") if address in p.name)
            if fichiers:
                break
        time.sleep(0.1)
    assert fichiers, f"aucun e-mail trouve pour {address} dans {emails_dir}"
    return fichiers[-1].read_text(encoding="utf-8")


def _extract_link_token(contenu: str, param: str) -> str:
    match = re.search(rf"{param}=([^\s&]+)", contenu)
    assert match, f"lien absent du contenu : {contenu!r}"
    return match.group(1)


def _register(page, frontend_server: str, email: str, org: str = "Acme SAS") -> None:
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", org)
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.click("#p-inscription button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_register_then_verify_email_via_real_link(page, frontend_server, backend_server):
    email = _email("verif")
    _register(page, frontend_server, email)
    expect(page.locator("#qui")).to_have_text(email)

    contenu = _latest_email_for(backend_server["storage_dir"], email)
    assert "Vérifiez votre adresse" in contenu
    token = _extract_link_token(contenu, "verify_email")

    page.goto(f"{frontend_server}/?verify_email={token}", wait_until="networkidle")
    page.wait_for_selector("#p-verification:not([hidden])")
    expect(page.locator("#msg-verification")).to_contain_text("vérifiée")


def test_login_wrong_password_shows_error(page, frontend_server, backend_server):
    email = _email("login")
    _register(page, frontend_server, email)
    page.click("button.lien:has-text(\"Fermer la session\")")
    page.wait_for_selector("#accueil:not([hidden])")

    page.fill("#c-mail", email)
    page.fill("#c-mdp", "MauvaisMotDePasse!123")
    page.click("#p-connexion button:not(.lien)")
    expect(page.locator(".alerte")).to_be_visible()
    expect(page.locator("#appli")).to_be_hidden()


def test_password_reset_full_round_trip(page, frontend_server, backend_server):
    email = _email("reset")
    new_pwd = "NouveauMdp!2026x"
    _register(page, frontend_server, email)
    page.click("button.lien:has-text(\"Fermer la session\")")
    page.wait_for_selector("#accueil:not([hidden])")

    page.click("button.lien:has-text(\"Mot de passe oublié\")")
    page.wait_for_selector("#p-oubli:not([hidden])")
    page.fill("#o-mail", email)
    page.click("#p-oubli button:not(.lien)")
    expect(page.locator(".succes")).to_be_visible()

    contenu = _latest_email_for(backend_server["storage_dir"], email)
    assert "Réinitialisation" in contenu
    token = _extract_link_token(contenu, "reset_password")

    page.goto(f"{frontend_server}/?reset_password={token}", wait_until="networkidle")
    page.wait_for_selector("#p-reinit:not([hidden])")
    page.fill("#r-mdp", new_pwd)
    page.click("#p-reinit button")
    expect(page.locator(".succes")).to_be_visible()

    page.fill("#c-mail", email)
    page.fill("#c-mdp", new_pwd)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
