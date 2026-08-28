"""Parcours d'authentification pilotes au vrai navigateur : inscription,
verification d'e-mail via le lien reellement envoye (repli fichier local),
connexion, mot de passe oublie de bout en bout.
"""

from __future__ import annotations

import uuid

from playwright.sync_api import expect

from conftest import extract_link_token, latest_email_for

PWD = "Compliance!2026x"


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@exemple.fr"


def _register(page, frontend_server: str, backend_server, email: str, org: str = "Acme SAS") -> None:
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", org)
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
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_register_then_verify_email_via_real_link(page, frontend_server, backend_server):
    """Le point precis impose par cette fonctionnalite : le compte existe des
    l'inscription, mais la connexion doit rester bloquee tant que le lien
    reellement envoye (repli fichier local) n'a pas ete ouvert."""
    email = _email("verif")
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.check("#i-cgu")
    page.click("#p-inscription button:not(.lien)")
    page.wait_for_selector("#p-connexion:not([hidden])")
    expect(page.locator("#msg-accueil")).to_contain_text("vérification")

    # Bloque tant que le lien n'a pas ete suivi.
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#p-connexion button:not(.lien)")
    expect(page.locator(".alerte")).to_contain_text("non verifiee")
    expect(page.locator("#appli")).to_be_hidden()

    contenu = latest_email_for(backend_server["storage_dir"], email)
    assert "Vérifiez votre adresse" in contenu
    token = extract_link_token(contenu, "verify_email")

    page.goto(f"{frontend_server}/?verify_email={token}", wait_until="networkidle")
    page.wait_for_selector("#p-verification:not([hidden])")
    expect(page.locator("#msg-verification")).to_contain_text("vérifiée")

    page.goto(frontend_server, wait_until="networkidle")
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_registration_requires_accepting_privacy_policy(page, frontend_server, backend_server):
    """Avant ce correctif, le frontend envoyait `accept_terms: true` en dur
    sans jamais montrer de case a cocher : le consentement trace cote
    serveur (table Consent) ne correspondait a rien de reellement accepte
    par la personne. Verifie aussi que la politique est consultable avant
    de s'inscrire, et que la case cochee ramene bien au formulaire rempli."""
    email = _email("cgu")
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)

    page.click("#p-inscription button:not(.lien)")
    expect(page.locator(".alerte")).to_contain_text("accepter")
    expect(page.locator("#appli")).to_be_hidden()

    page.click("text=conditions d'utilisation et la politique de confidentialité")
    page.wait_for_selector("#p-confidentialite:not([hidden])")
    expect(page.get_by_text("Sous-traitants")).to_be_visible()
    page.click("button.lien:has-text(\"Retour à l'inscription\")")
    page.wait_for_selector("#p-inscription:not([hidden])")

    # Les champs remplis avant l'ouverture de la politique doivent survivre.
    expect(page.locator("#i-mail")).to_have_value(email)

    page.check("#i-cgu")
    page.click("#p-inscription button:not(.lien)")
    page.wait_for_selector("#p-connexion:not([hidden])")
    expect(page.locator("#msg-accueil")).to_contain_text("vérification")


def test_login_wrong_password_shows_error(page, frontend_server, backend_server):
    email = _email("login")
    _register(page, frontend_server, backend_server, email)
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
    _register(page, frontend_server, backend_server, email)
    page.click("button.lien:has-text(\"Fermer la session\")")
    page.wait_for_selector("#accueil:not([hidden])")

    page.click("button.lien:has-text(\"Mot de passe oublié\")")
    page.wait_for_selector("#p-oubli:not([hidden])")
    page.fill("#o-mail", email)
    page.click("#p-oubli button:not(.lien)")
    expect(page.locator(".succes")).to_be_visible()

    contenu = latest_email_for(backend_server["storage_dir"], email)
    assert "Réinitialisation" in contenu
    token = extract_link_token(contenu, "reset_password")

    page.goto(f"{frontend_server}/?reset_password={token}", wait_until="networkidle")
    page.wait_for_selector("#p-reinit:not([hidden])")
    page.fill("#r-mdp", new_pwd)
    page.click("#p-reinit button:not(.lien)")
    expect(page.locator(".succes")).to_be_visible()

    page.fill("#c-mail", email)
    page.fill("#c-mdp", new_pwd)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
