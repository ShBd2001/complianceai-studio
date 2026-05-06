"""Le badge et le fil de notifications, pilotes au navigateur — la
notification elle-meme est creee directement en base (comme le ferait la
veille reglementaire ou une campagne planifiee en production), pas via l'UI :
ce n'est pas ce qui est teste ici.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

from playwright.sync_api import expect

PWD = "Compliance!2026x"


def _register(page, frontend_server: str, email: str) -> str:
    page.goto(frontend_server, wait_until="networkidle")
    page.click("button.lien:has-text(\"Créer un compte\")")
    page.wait_for_selector("#p-inscription:not([hidden])")
    page.fill("#i-nom", "Sarah Test")
    page.fill("#i-org", "Acme SAS")
    page.fill("#i-mail", email)
    page.fill("#i-mdp", PWD)
    page.click("#p-inscription button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)
    return page.locator("#ch-org-global option").first.get_attribute("value")


def _create_notification(env_e2e, backend_server, org_id: str, title: str) -> None:
    """Cree une notification directement en base, dans le processus API (pas
    le processus de test) : execute un script Python avec le meme
    environnement/DATABASE_URL que le serveur demarre par backend_server."""
    import subprocess

    script = f"""
from app.db.session import SessionLocal
from app.services.notifications import notify

with SessionLocal() as db:
    notify(db, organization_id="{org_id}", kind="test.e2e",
           title="{title}", body="Corps de test E2E.", notify_by_email=False)
    db.commit()
"""
    env = dict(env_e2e)
    env["STORAGE_DIR"] = str(backend_server["storage_dir"])
    env["PYTHONPATH"] = str(Path(__file__).parents[2] / "backend")
    subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).parents[2] / "backend", env=env, check=True,
    )


def test_notification_appears_with_badge(page, frontend_server, backend_server, env_e2e):
    email = f"notif-{uuid.uuid4().hex[:8]}@exemple.fr"
    org_id = _register(page, frontend_server, email)

    _create_notification(env_e2e, backend_server, org_id, "Alerte E2E")

    # Le jeton d'acces vit en memoire JS (pas de session persistee) : le badge
    # se recalcule a la connexion, pas via un rafraichissement en direct.
    # Se deconnecter puis se reconnecter est donc le vrai chemin, pas un
    # rechargement de page qui perdrait la session comme n'importe quel
    # rechargement en conditions reelles.
    page.click("button.lien:has-text(\"Fermer la session\")")
    page.wait_for_selector("#accueil:not([hidden])")
    page.fill("#c-mail", email)
    page.fill("#c-mdp", PWD)
    page.click("#p-connexion button:not(.lien)")
    page.wait_for_selector("#appli:not([hidden])", timeout=15000)

    expect(page.locator("#badge-notifs")).to_be_visible()

    page.click("a[data-vue=\"notifications\"]")
    page.wait_for_selector(".journal")
    expect(page.get_by_text("Alerte E2E")).to_be_visible()

    # La visite marque le fil comme vu : le badge disparait.
    expect(page.locator("#badge-notifs")).to_be_hidden()
