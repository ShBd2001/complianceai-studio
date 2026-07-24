"""Pages ajoutees pour exposer des routes backend qui existaient sans
interface : referentiels (articles/versions), « Mon compte » (creation
d'organisation, changement de mot de passe, deconnexion reelle, export RGPD),
et la page « A propos » (contenu statique, disclaimers, contact).
"""

from __future__ import annotations

import uuid

from playwright.sync_api import expect

from conftest import extract_link_token, latest_email_for

PWD = "Compliance!2026x"


def _register(page, frontend_server: str, backend_server, email: str) -> None:
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
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


def test_referentiels_page_lists_articles_and_current_version(page, frontend_server, backend_server):
    email = f"ref-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"referentiels\"]")
    page.wait_for_selector("#z-req table", timeout=15000)

    expect(page.get_by_text("Version en vigueur")).to_be_visible()
    assert page.locator("#z-req tbody tr").count() > 0

    # Le filtre « perimetre auditable » doit reduire la liste (articles
    # structurels comme les definitions en sont exclus).
    total = page.locator("#z-req tbody tr").count()
    page.check("#ref-auditable")
    page.wait_for_timeout(400)
    auditable = page.locator("#z-req tbody tr").count()
    assert auditable < total


def test_create_organization_from_account_page(page, frontend_server, backend_server):
    email = f"acc-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)

    avant = page.locator("#ch-org-global option").count()
    page.fill("#co-nom", "Deuxième organisation")
    page.click("#btn-creer-org")
    expect(page.locator("#msg-org .succes")).to_be_visible()
    assert page.locator("#ch-org-global option").count() == avant + 1


def test_change_password_from_account_page(page, frontend_server, backend_server):
    email = f"pwd-{uuid.uuid4().hex[:8]}@exemple.fr"
    new_pwd = "AutreMotDePasse!2026x"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)
    page.fill("#cp-actuel", PWD)
    page.fill("#cp-nouveau", new_pwd)
    page.click("#btn-changer-mdp")
    expect(page.locator("#msg-secu .succes")).to_be_visible()

    page.click("button.lien:has-text(\"Fermer la session\")")
    page.wait_for_selector("#accueil:not([hidden])")
    page.fill("#c-mail", email)
    page.fill("#c-mdp", new_pwd)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_logout_actually_revokes_the_server_session(page, frontend_server, backend_server):
    """Le point precis qui manquait avant cette fonctionnalite : « Fermer la
    session » se contentait de recharger la page, sans jamais revoquer le
    jeton de rafraichissement cote serveur."""
    email = f"logout-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("button.lien:has-text(\"Fermer la session\")")
    page.wait_for_selector("#accueil:not([hidden])")

    # Le cookie de rafraichissement (httpOnly) est toujours dans le contexte
    # du navigateur : s'il etait encore valide cote serveur, /auth/refresh
    # reussirait malgre la deconnexion affichee a l'ecran.
    resp = page.context.request.post(f"{backend_server['url']}/api/v1/auth/refresh")
    assert resp.status == 401


def test_delete_organization_then_delete_account(page, frontend_server, backend_server):
    """Le point precis remonte en retour utilisateur : la suppression de
    compte echouait ("vous etes owner d'une organisation") sans qu'aucun
    bouton n'existe nulle part pour supprimer cette organisation."""
    email = f"delcompte-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)

    page.once("dialog", lambda d: d.accept())
    page.click("#z-orgs button:has-text(\"Supprimer\")")
    expect(page.locator("#msg-org .succes")).to_be_visible()
    expect(page.get_by_text("Aucune organisation.")).to_be_visible()

    page.once("dialog", lambda d: d.accept())
    page.click("button:has-text(\"Supprimer mon compte\")")
    page.wait_for_selector("#accueil:not([hidden])", timeout=15000)


def test_about_page_has_content_and_contact_link(page, frontend_server, backend_server):
    email = f"apropos-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"apropos\"]")
    page.wait_for_selector("a[href^='mailto:']", timeout=10000)

    expect(page.get_by_text("manquement par défaut")).to_be_visible()
    expect(page.get_by_text("Ce que ce n'est pas")).to_be_visible()
    assert page.locator("a[href^='mailto:']").get_attribute("href").startswith("mailto:")
