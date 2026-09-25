"""Pages ajoutees pour exposer des routes backend qui existaient sans
interface : referentiels (articles/versions), « Mon compte » (creation
d'organisation, changement de mot de passe, deconnexion reelle, export RGPD),
et la page « A propos » (contenu statique, disclaimers, contact).
"""

from __future__ import annotations

import uuid

from playwright.sync_api import expect

from conftest import extract_link_token, latest_email_for, passer_tour_si_present

PWD = "Compliance!2026x"


def _register(page, frontend_server: str, backend_server, email: str) -> None:
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
    passer_tour_si_present(page)


def test_referentiels_page_lists_articles_and_current_version(page, frontend_server, backend_server):
    """Le nom du test date d'avant le retrait volontaire des notes
    d'ingestion internes (commit 990e79a) : la page ne montre plus la
    version/empreinte, uniquement les articles eux-memes desormais."""
    email = f"ref-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"referentiels\"]")
    page.wait_for_selector("#z-req table", timeout=15000)

    assert page.locator("#z-req tbody tr").count() > 0

    # Le filtre « perimetre auditable » doit reduire la liste (articles
    # structurels comme les definitions en sont exclus).
    total = page.locator("#z-req tbody tr").count()
    page.check("#ref-auditable")
    page.wait_for_timeout(400)
    auditable = page.locator("#z-req tbody tr").count()
    assert auditable < total


def test_referentiel_article_expands_to_show_full_text_and_is_searchable(page, frontend_server, backend_server):
    """Le texte integral d'un article (deja recupere par l'API mais jamais
    affiche auparavant) doit etre consultable en un clic, et la recherche
    doit filtrer sur le contenu reel du texte, pas seulement le titre."""
    email = f"reftxt-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"referentiels\"]")
    page.wait_for_selector("#z-req table", timeout=15000)

    premiere_ligne = page.locator(".req-ligne").first
    premiere_ligne.click()
    expect(page.locator(".req-detail-ligne").first).to_be_visible()
    expect(page.locator(".req-corps").first).not_to_have_text("")
    expect(premiere_ligne).to_have_attribute("aria-expanded", "true")

    # "violation" n'apparait que dans le corps de l'article 33 du referentiel
    # factice utilise par cette suite (voir _seed.py) : un mot present dans
    # le texte integral mais absent du titre prouve que la recherche filtre
    # bien sur le corps de l'article, pas seulement sur reference/titre.
    total = page.locator(".req-ligne").count()
    page.fill("#req-recherche", "violation")
    page.wait_for_timeout(400)
    filtre = page.locator(".req-ligne").count()
    assert 0 < filtre < total


def test_create_organization_from_account_page(page, frontend_server, backend_server):
    """Une organisation fraichement creee redirige directement vers sa page
    de profil d'eligibilite dediee (#/organisation/{id}), plutot que de
    rester sur "Mon compte" avec un simple message de succes -- elle n'a
    encore aucune reponse, autant guider tout de suite vers le formulaire
    qui les recueille."""
    email = f"acc-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)

    avant = page.locator("#ch-org-global option").count()
    page.fill("#co-nom", "Deuxième organisation")
    page.click("#btn-creer-org")

    # 20s plutot que les 15s habituels : la redirection enchaine deux allers-
    # retours reseau (creation, puis GET du profil de la nouvelle organisation)
    # au lieu d'un rendu local immediat.
    page.wait_for_selector("#profil-onglets", timeout=20000)
    expect(page.locator("h1")).to_have_text("Deuxième organisation")
    assert "#/organisation/" in page.url
    assert page.locator("#ch-org-global option").count() == avant + 1
    # La nouvelle organisation devient l'organisation active (pas seulement
    # affichee dans le commutateur).
    expect(page.locator("#ch-org-global")).to_have_value(page.url.rsplit("/", 1)[-1])

    # Depuis "Mon compte", chaque organisation propose son propre lien vers
    # cette page -- verifie qu'on peut y revenir plus tard, pas seulement a
    # la creation.
    page.click("text=Retour à Mon compte")
    page.wait_for_selector("#z-orgs table", timeout=15000)
    expect(page.locator("#z-orgs table")).to_contain_text("Profil d'éligibilité")


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

    page.click("button.rail-sortie:has-text(\"Fermer la session\")")
    page.wait_for_selector("#lancement:not([hidden])")
    page.click(".lance-connexion")
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

    page.click("button.rail-sortie:has-text(\"Fermer la session\")")
    page.wait_for_selector("#lancement:not([hidden])")

    # Le cookie de rafraichissement (httpOnly) est toujours dans le contexte
    # du navigateur : s'il etait encore valide cote serveur, /auth/refresh
    # reussirait malgre la deconnexion affichee a l'ecran.
    resp = page.context.request.post(f"{backend_server['url']}/api/v1/auth/refresh")
    assert resp.status == 401


def test_session_survives_a_page_reload(page, frontend_server, backend_server):
    """Retour utilisateur : actualiser la page deconnectait systematiquement,
    car le jeton d'acces ne vivait qu'en memoire JS (variable E.jeton),
    jamais persiste. Desormais restaurerSession() relit le jeton depuis
    localStorage au demarrage (ou le renouvelle via /auth/refresh s'il a
    expire) avant d'afficher l'ecran de connexion."""
    email = f"reload-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    assert page.evaluate("!!localStorage.getItem('cai_jeton')")

    page.reload(wait_until="networkidle")
    page.wait_for_selector("#appli:not([hidden])", timeout=10000)

    # Une deconnexion explicite doit rester definitive apres actualisation.
    page.click("button.rail-sortie:has-text(\"Fermer la session\")")
    page.wait_for_selector("#lancement:not([hidden])")
    assert page.evaluate("localStorage.getItem('cai_jeton')") is None
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#lancement:not([hidden])", timeout=10000)


def test_delete_organization_then_delete_account(page, frontend_server, backend_server):
    """Le point precis remonte en retour utilisateur : la suppression de
    compte echouait ("vous etes owner d'une organisation") sans qu'aucun
    bouton n'existe nulle part pour supprimer cette organisation."""
    email = f"delcompte-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    # Gestionnaire permanent plutot que page.once() reenregistre entre les
    # deux confirm() de ce test : deux "once" consecutifs laissent une
    # fenetre ou le second clic peut survenir avant le reenregistrement,
    # auto-rejetant alors sa boite de dialogue (comportement par defaut de
    # Playwright sans gestionnaire arme) -- cause plausible du flake constate
    # (organisation jamais supprimee, capture d'echec a l'appui).
    page.on("dialog", lambda d: d.accept())

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)

    page.click("#z-orgs button:has-text(\"Supprimer\")")
    expect(page.locator("#msg-org .succes")).to_be_visible()
    expect(page.get_by_text("Aucune organisation.")).to_be_visible()

    page.click("button:has-text(\"Supprimer mon compte\")")
    page.wait_for_selector("#lancement:not([hidden])", timeout=15000)


def _register_cabinet(page, frontend_server: str, backend_server, email: str) -> None:
    """Comme _register(), mais en passant par la page Tarifs pour souscrire
    a l'offre Cabinet -- seule offre sur laquelle la retention personnalisee
    des documents est proposee (voir rendreRetention() dans index.html)."""
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-tarifs")
    page.wait_for_selector("#tarifs:not([hidden])")
    page.click("button.plan-cta:has-text('Choisir Cabinet')")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Cabinet Test SAS")
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
    passer_tour_si_present(page)


def test_retention_control_visible_and_usable_for_cabinet_owner(page, frontend_server, backend_server):
    email = f"retention-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register_cabinet(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)
    expect(page.locator("h2:has-text('Rétention des documents')")).to_be_visible()

    # Sous le plancher de 30 jours : rejete cote client, avant tout appel serveur.
    page.fill("#co-retention", "5")
    page.click("#btn-retention")
    expect(page.locator("#msg-retention .alerte")).to_be_visible()

    page.fill("#co-retention", "90")
    page.click("#btn-retention")
    expect(page.locator("#msg-retention .succes")).to_be_visible()

    # La valeur enregistree cote serveur doit survivre a un rechargement.
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)
    expect(page.locator("#co-retention")).to_have_value("90")


def test_retention_control_hidden_for_non_cabinet_plan(page, frontend_server, backend_server):
    email = f"noretention-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)  # offre Essentiel par defaut

    page.click("a[data-vue=\"compte\"]")
    page.wait_for_selector("#z-orgs table", timeout=15000)
    expect(page.locator("h2:has-text('Rétention des documents')")).to_have_count(0)


def test_about_page_has_content_and_contact_link(page, frontend_server, backend_server):
    email = f"apropos-{uuid.uuid4().hex[:8]}@exemple.fr"
    _register(page, frontend_server, backend_server, email)

    page.click("a[data-vue=\"apropos\"]")
    page.wait_for_selector("#vue a[href^='mailto:']", timeout=10000)

    expect(page.get_by_text("manquement par défaut")).to_be_visible()
    expect(page.get_by_text("Ce que ce n'est pas")).to_be_visible()
    assert page.locator("#vue a[href^='mailto:']").get_attribute("href").startswith("mailto:")
