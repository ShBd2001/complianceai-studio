"""Changement d'offre apres la creation de l'organisation.

Avant ce correctif, `plan` n'etait fixe qu'a l'inscription (OrganizationCreate)
et jamais modifiable ensuite -- alors que le message de quota epuise
promettait explicitement "il suffit de passer au palier superieur depuis
votre espace Mon compte". PATCH /orgs/{org_id}/plan comble cet ecart.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.main import app
from conftest import verify_email

PWD = "Compliance!2026x"


def _email() -> str:
    return f"plan-{uuid.uuid4().hex[:10]}@exemple.fr"


def client() -> TestClient:
    return TestClient(app)


def _register(c: TestClient, email: str, org: str, plan: str) -> dict:
    r = c.post("/api/v1/auth/register", json={
        "email": email, "password": PWD, "full_name": "Sarah Test",
        "organization_name": org, "accept_terms": True, "plan": plan,
    })
    assert r.status_code == 201, r.text
    verify_email(c, email)
    return r.json()


def _login(c: TestClient, email: str) -> str:
    r = c.post("/api/v1/auth/login", json={"email": email, "password": PWD})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_owner_peut_changer_d_offre():
    c = client()
    email = _email()
    owner = _register(c, email, "Croissance SAS", plan="essentiel")
    org_id = owner["memberships"][0]["organization_id"]
    token = _login(c, email)

    r = c.patch(f"/api/v1/orgs/{org_id}/plan", json={"plan": "pro"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "pro"

    # Persiste reellement, pas seulement dans la reponse de la requete.
    r = c.get(f"/api/v1/orgs/{org_id}", headers=_auth(token))
    assert r.json()["plan"] == "pro"


def test_admin_ne_peut_pas_changer_d_offre():
    c = client()
    owner_email, admin_email = _email(), _email()
    owner = _register(c, owner_email, "Cabinet Sigma", plan="pro")
    org_id = owner["memberships"][0]["organization_id"]
    owner_token = _login(c, owner_email)

    _register(c, admin_email, "Autre SAS", plan="essentiel")
    r = c.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": admin_email, "role": "admin"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 201
    admin_token = _login(c, admin_email)

    r = c.patch(f"/api/v1/orgs/{org_id}/plan", json={"plan": "cabinet"}, headers=_auth(admin_token))
    assert r.status_code == 403  # un admin n'est pas un owner


def test_downgrade_refuse_si_effectif_depasse_la_nouvelle_limite():
    """Offre Pro : jusqu'a 3 membres. Redescendre vers Essentiel (limite 1)
    avec 2 membres doit etre refuse -- l'API ne choisit jamais qui retirer."""
    c = client()
    owner_email, second_email = _email(), _email()
    owner = _register(c, owner_email, "Cabinet Tau", plan="pro")
    org_id = owner["memberships"][0]["organization_id"]
    owner_token = _login(c, owner_email)

    _register(c, second_email, "Autre SAS 2", plan="essentiel")
    r = c.post(
        f"/api/v1/orgs/{org_id}/members",
        json={"email": second_email, "role": "auditor"},
        headers=_auth(owner_token),
    )
    assert r.status_code == 201

    r = c.patch(f"/api/v1/orgs/{org_id}/plan", json={"plan": "essentiel"}, headers=_auth(owner_token))
    assert r.status_code == 409

    # L'offre n'a pas bouge.
    r = c.get(f"/api/v1/orgs/{org_id}", headers=_auth(owner_token))
    assert r.json()["plan"] == "pro"


def test_downgrade_autorise_si_effectif_compatible():
    c = client()
    email = _email()
    owner = _register(c, email, "Cabinet Upsilon", plan="cabinet")
    org_id = owner["memberships"][0]["organization_id"]
    token = _login(c, email)

    # Un seul membre (le proprietaire) : compatible avec la limite Essentiel (1).
    r = c.patch(f"/api/v1/orgs/{org_id}/plan", json={"plan": "essentiel"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["plan"] == "essentiel"


def test_quitter_cabinet_reinitialise_la_retention_personnalisee():
    """La retention personnalisee (PATCH /retention) est reservee a l'offre
    Cabinet : la laisser active apres en etre sorti serait une purge
    automatique silencieuse, sur un reglage devenu invisible dans
    l'interface (rendreRetention() ne s'affiche que pour l'offre Cabinet)."""
    c = client()
    email = _email()
    owner = _register(c, email, "Cabinet Phi", plan="cabinet")
    org_id = owner["memberships"][0]["organization_id"]
    token = _login(c, email)

    r = c.patch(f"/api/v1/orgs/{org_id}/retention",
                json={"document_retention_days": 90}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["document_retention_days"] == 90

    r = c.patch(f"/api/v1/orgs/{org_id}/plan", json={"plan": "pro"}, headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["document_retention_days"] is None
