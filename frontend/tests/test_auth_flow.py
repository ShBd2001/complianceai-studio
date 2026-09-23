"""Parcours d'authentification pilotes au vrai navigateur : inscription,
verification d'e-mail via le lien reellement envoye (repli fichier local),
connexion, mot de passe oublie de bout en bout.
"""

from __future__ import annotations

import base64
import json
import uuid

from playwright.sync_api import expect

from conftest import extract_link_token, latest_email_for

PWD = "Compliance!2026x"


def _email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}@exemple.fr"


def _jwt_stub(payload: dict) -> str:
    """Un jeton syntaxiquement conforme a un JWT mais non signe : suffisant
    ici, le frontend ne fait que decoder le payload pour pre-remplir
    l'affichage (voir gererIdentifiantFournisseur dans index.html) -- il ne
    verifie jamais la signature lui-meme, c'est le role exclusif du backend
    (app/core/security.py::decode_google_id_token / decode_microsoft_id_token,
    deja couvert avec un decodeur factice dans backend/tests/test_google_auth.py
    et test_microsoft_auth.py)."""
    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    entete = _b64url(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
    corps = _b64url(json.dumps(payload).encode())
    return f"{entete}.{corps}.signature-non-verifiee-cote-client"


def _register(page, frontend_server: str, backend_server, email: str, org: str = "Acme SAS") -> None:
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-inscription")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", org)
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.check("#i-cgu")
    page.click("#btn-inscription")
    page.wait_for_selector("#p-connexion:not([hidden])")

    contenu = latest_email_for(backend_server["storage_dir"], email)
    token = extract_link_token(contenu, "verify_email")
    page.goto(f"{frontend_server}/?verify_email={token}", wait_until="networkidle")
    page.wait_for_selector("#p-verification:not([hidden])")

    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-connexion")
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#btn-connexion")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_theme_and_language_toggles_persist_across_reload(page, frontend_server, backend_server):
    """Les deux boutons du coin superieur droit (mode sombre, FR/EN) doivent
    changer l'affichage immediatement et survivre a une actualisation, avant
    ET apres connexion — pas seulement un etat JS en memoire."""
    email = _email("theme")
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-connexion")

    expect(page.locator("html")).not_to_have_attribute("data-theme", "dark")
    page.click("#rr-theme")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")

    page.click("#rr-langue")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("#btn-connexion")).to_have_text("Sign in")

    page.reload(wait_until="networkidle")
    page.click(".lance-connexion")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.locator("html")).to_have_attribute("lang", "en")
    expect(page.locator("#btn-connexion")).to_have_text("Sign in")

    # Bascule retour en francais pour s'inscrire avec le flux standard
    # (verify_email/latest_email_for ne dependent pas de la langue, mais on
    # verifie ici que re-basculer fonctionne aussi dans ce sens).
    page.click("#rr-langue")
    expect(page.locator("html")).not_to_have_attribute("lang", "en")
    expect(page.locator("#btn-connexion")).to_have_text("Se connecter")

    _register(page, frontend_server, backend_server, email)
    expect(page.locator("a[data-vue=\"tableau\"]")).to_be_visible()

    # L'etat sombre pose avant la connexion doit rester actif dans l'appli.
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.reload(wait_until="networkidle")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")


def test_register_then_verify_email_via_real_link(page, frontend_server, backend_server):
    """Le point precis impose par cette fonctionnalite : le compte existe des
    l'inscription, mais la connexion doit rester bloquee tant que le lien
    reellement envoye (repli fichier local) n'a pas ete ouvert."""
    email = _email("verif")
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-inscription")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.check("#i-cgu")
    page.click("#btn-inscription")
    page.wait_for_selector("#p-connexion:not([hidden])")
    expect(page.locator("#msg-accueil")).to_contain_text("vérification")

    # Bloque tant que le lien n'a pas ete suivi.
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#btn-connexion")
    expect(page.locator(".alerte")).to_contain_text("non verifiee")
    expect(page.locator("#appli")).to_be_hidden()

    contenu = latest_email_for(backend_server["storage_dir"], email)
    assert "Vérifiez votre adresse" in contenu
    token = extract_link_token(contenu, "verify_email")

    page.goto(f"{frontend_server}/?verify_email={token}", wait_until="networkidle")
    page.wait_for_selector("#p-verification:not([hidden])")
    expect(page.locator("#msg-verification")).to_contain_text("vérifiée")

    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-connexion")
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#btn-connexion")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


def test_registration_requires_accepting_privacy_policy(page, frontend_server, backend_server):
    """Avant ce correctif, le frontend envoyait `accept_terms: true` en dur
    sans jamais montrer de case a cocher : le consentement trace cote
    serveur (table Consent) ne correspondait a rien de reellement accepte
    par la personne. Verifie aussi que la politique est consultable avant
    de s'inscrire, et que la case cochee ramene bien au formulaire rempli."""
    email = _email("cgu")
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-inscription")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)

    page.click("#btn-inscription")
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
    page.click("#btn-inscription")
    page.wait_for_selector("#p-connexion:not([hidden])")
    expect(page.locator("#msg-accueil")).to_contain_text("vérification")


def test_login_wrong_password_shows_error(page, frontend_server, backend_server):
    email = _email("login")
    _register(page, frontend_server, backend_server, email)
    page.click("button.rail-sortie:has-text(\"Fermer la session\")")
    page.wait_for_selector("#lancement:not([hidden])")
    page.click(".lance-connexion")

    page.fill("#c-mail", email)
    page.fill("#c-mdp", "MauvaisMotDePasse!123")
    page.click("#btn-connexion")
    expect(page.locator(".alerte")).to_be_visible()
    expect(page.locator("#appli")).to_be_hidden()


def test_password_reset_full_round_trip(page, frontend_server, backend_server):
    email = _email("reset")
    new_pwd = "NouveauMdp!2026x"
    _register(page, frontend_server, backend_server, email)
    page.click("button.rail-sortie:has-text(\"Fermer la session\")")
    page.wait_for_selector("#lancement:not([hidden])")
    page.click(".lance-connexion")

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
    page.click("#btn-connexion")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)


# --------------------------------------------------------------------------
# "Se connecter avec Google" -- le vrai bouton Google (bibliotheque externe,
# ID client OAuth reel, compte Google reel) n'est pas testable en CI : ces
# tests invoquent directement le rappel qu'il declencherait (gererIdentifiant
# Google) et interceptent les appels a l'API (page.route) pour isoler la
# logique frontend -- la verification du jeton cote serveur est deja
# couverte, avec un decodeur factice, dans backend/tests/test_google_auth.py.
# --------------------------------------------------------------------------
def test_google_signin_new_user_completes_onboarding(page, frontend_server, backend_server):
    page.goto(frontend_server, wait_until="networkidle")
    # Le bouton Google (et donc gererIdentifiantFournisseur) ne vit que dans
    # #accueil, qui n'est montre qu'apres ce clic depuis la page d'atterrissage.
    page.click(".lance-connexion")
    page.wait_for_selector("#p-connexion:not([hidden])")

    page.route("**/api/v1/auth/google/login", lambda route: route.fulfill(
        status=404, content_type="application/json",
        body=json.dumps({"detail": "Aucun compte pour cette adresse. Inscrivez-vous d'abord avec Google."}),
    ))

    requetes_inscription = []

    def repondre_inscription(route):
        requetes_inscription.append(json.loads(route.request.post_data))
        route.fulfill(status=409, content_type="application/json",
                       body=json.dumps({"detail": "Un compte existe deja pour cette adresse."}))
    page.route("**/api/v1/auth/google/register", repondre_inscription)

    jeton = _jwt_stub({
        "email": "nouvelle-personne@exemple.fr", "name": "Nouvelle Personne", "email_verified": True,
    })
    page.evaluate("jeton => gererIdentifiantFournisseur('google', jeton)", jeton)

    page.wait_for_selector("#p-inscription:not([hidden])")
    expect(page.locator("#i-mail")).to_have_value("nouvelle-personne@exemple.fr")
    expect(page.locator("#i-nom")).to_have_value("Nouvelle Personne")
    expect(page.locator("#champ-mdp-inscription")).to_be_hidden()
    expect(page.locator("#btn-inscription")).to_have_text("Finaliser la création du compte")

    page.fill("#i-org", "Cabinet Playwright")
    page.check("#i-cgu")
    page.click("#btn-inscription")

    expect(page.locator("#msg-accueil .alerte")).to_be_visible()
    assert len(requetes_inscription) == 1
    assert requetes_inscription[0]["organization_name"] == "Cabinet Playwright"
    assert requetes_inscription[0]["accept_terms"] is True
    assert requetes_inscription[0]["id_token"] == jeton


def test_google_signin_existing_user_logs_in_directly(page, frontend_server, backend_server):
    page.goto(frontend_server, wait_until="networkidle")
    page.click(".lance-connexion")
    page.wait_for_selector("#p-connexion:not([hidden])")

    page.route("**/api/v1/auth/google/login", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"access_token": "jeton-acces-factice", "token_type": "bearer", "expires_in": 900}),
    ))

    jeton = _jwt_stub({
        "email": "deja-inscrite@exemple.fr", "name": "Deja Inscrite", "email_verified": True,
    })
    page.evaluate("jeton => gererIdentifiantFournisseur('google', jeton)", jeton)

    # definirJeton() persiste le jeton avant meme que demarrer() ne charge le
    # profil : suffisant pour prouver que la reponse 200 a ete traitee comme
    # une connexion reussie, sans dependre du reste du demarrage de
    # l'application (deja couvert par les autres tests de ce fichier).
    page.wait_for_function("localStorage.getItem('cai_jeton') === 'jeton-acces-factice'")


# --------------------------------------------------------------------------
# "Se connecter avec Microsoft" -- pas de bouton pret a l'emploi comme
# Google (MSAL.js impose un bundler, incompatible avec ce depot sans etape
# de build, voir index.html::lancerConnexionMicrosoft), donc une redirection
# pleine page vers login.microsoftonline.com puis un retour sur cette meme
# page avec le jeton dans le fragment d'URL. Teste ici en simulant
# directement ce retour (sessionStorage pose comme le ferait
# lancerConnexionMicrosoft, puis navigation vers l'URL de retour avec le
# fragment) plutot qu'en cliquant un vrai bouton qui redirigerait
# reellement vers Microsoft -- impossible a completer sans compte Azure AD
# reel en CI.
# --------------------------------------------------------------------------
def _poser_nonce_state_microsoft(page) -> tuple[str, str]:
    return tuple(page.evaluate("""() => {
        const nonce = crypto.randomUUID(), state = crypto.randomUUID();
        sessionStorage.setItem('ms_nonce', nonce);
        sessionStorage.setItem('ms_state', state);
        return [nonce, state];
    }"""))


def _retour_microsoft(page, frontend_server, id_token: str, state: str) -> None:
    # Un changement de fragment seul (#...) sur la MEME page est traite par
    # le navigateur comme une navigation interne, sans re-executer les
    # <script> -- contrairement au vrai aller-retour cross-origin via
    # Microsoft que ceci doit simuler. Le passage par about:blank force un
    # rechargement complet, comme le ferait cette vraie redirection.
    page.goto("about:blank")
    page.goto(f"{frontend_server}/#id_token={id_token}&state={state}", wait_until="networkidle")


def test_microsoft_signin_new_user_completes_onboarding(page, frontend_server, backend_server):
    page.goto(frontend_server, wait_until="networkidle")
    nonce, state = _poser_nonce_state_microsoft(page)
    jeton = _jwt_stub({"email": "nouvelle-personne-ms@exemple.fr", "name": "Nouvelle Personne MS", "nonce": nonce})

    page.route("**/api/v1/auth/microsoft/login", lambda route: route.fulfill(
        status=404, content_type="application/json",
        body=json.dumps({"detail": "Aucun compte pour cette adresse. Inscrivez-vous d'abord avec Microsoft."}),
    ))
    requetes_inscription = []

    def repondre_inscription(route):
        requetes_inscription.append(json.loads(route.request.post_data))
        route.fulfill(status=409, content_type="application/json",
                       body=json.dumps({"detail": "Un compte existe deja pour cette adresse."}))
    page.route("**/api/v1/auth/microsoft/register", repondre_inscription)

    _retour_microsoft(page, frontend_server, jeton, state)

    page.wait_for_selector("#p-inscription:not([hidden])")
    expect(page.locator("#i-mail")).to_have_value("nouvelle-personne-ms@exemple.fr")
    expect(page.locator("#i-nom")).to_have_value("Nouvelle Personne MS")
    expect(page.locator("#champ-mdp-inscription")).to_be_hidden()

    page.fill("#i-org", "Cabinet Microsoft Playwright")
    page.check("#i-cgu")
    page.click("#btn-inscription")

    expect(page.locator("#msg-accueil .alerte")).to_be_visible()
    assert len(requetes_inscription) == 1
    assert requetes_inscription[0]["organization_name"] == "Cabinet Microsoft Playwright"
    assert requetes_inscription[0]["id_token"] == jeton


def test_microsoft_signin_existing_user_logs_in_directly(page, frontend_server, backend_server):
    page.goto(frontend_server, wait_until="networkidle")
    nonce, state = _poser_nonce_state_microsoft(page)
    jeton = _jwt_stub({"email": "deja-inscrite-ms@exemple.fr", "nonce": nonce})

    page.route("**/api/v1/auth/microsoft/login", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"access_token": "jeton-acces-microsoft-factice", "token_type": "bearer", "expires_in": 900}),
    ))

    _retour_microsoft(page, frontend_server, jeton, state)
    page.wait_for_function("localStorage.getItem('cai_jeton') === 'jeton-acces-microsoft-factice'")


def test_microsoft_signin_rejects_forged_state(page, frontend_server, backend_server):
    """Le parametre "state" protege la redirection elle-meme (CSRF) : un
    retour dont le state ne correspond pas a celui pose avant de partir vers
    Microsoft ne doit declencher aucun appel au serveur, quel que soit le
    contenu du jeton fourni."""
    page.goto(frontend_server, wait_until="networkidle")
    _, _ = _poser_nonce_state_microsoft(page)
    jeton = _jwt_stub({"email": "attaquant@exemple.fr", "nonce": "nonce-quelconque"})

    appels = []
    page.route("**/api/v1/auth/microsoft/login", lambda route: (appels.append(1), route.abort()))

    _retour_microsoft(page, frontend_server, jeton, "state-falsifie")
    page.wait_for_timeout(500)
    assert appels == []
    expect(page.locator("#lancement")).to_be_visible()
