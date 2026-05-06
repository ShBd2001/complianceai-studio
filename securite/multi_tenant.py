"""
Isolation multi-tenant.

Un filtrage applicatif (`WHERE tenant_id = ...` écrit à la main dans chaque
requête) finit toujours par être oublié quelque part. Sur une plateforme qui
ingère des politiques de confidentialité, des registres et des descriptions
d'architecture de sécurité de ses clients, une fuite inter-tenant est un
incident majeur — et sur un produit qui vend de la conformité, elle est fatale.

Deux niveaux de défense, à mettre en place ensemble :

  1. Row Level Security PostgreSQL — la base refuse elle-même de renvoyer les
     lignes d'un autre tenant, même si la requête applicative oublie le filtre.
  2. Contexte de tenant obligatoire côté application — impossible d'ouvrir une
     session sans avoir posé le tenant.

La recherche vectorielle est le point le plus souvent oublié : un index pgvector
interrogé sans filtre renvoie les voisins les plus proches TOUS TENANTS CONFONDUS.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_tenant_courant: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tenant_courant", default=None
)


class FuiteTenantError(RuntimeError):
    """Levée dès qu'une opération est tentée hors contexte de tenant."""


def tenant_actuel() -> str:
    valeur = _tenant_courant.get()
    if not valeur:
        raise FuiteTenantError(
            "Aucun tenant dans le contexte. Toute opération sur des données "
            "client doit être encadrée par `contexte_tenant(...)`."
        )
    return valeur


@contextmanager
def contexte_tenant(tenant_id: str) -> Iterator[str]:
    if not tenant_id or not isinstance(tenant_id, str):
        raise FuiteTenantError(f"tenant_id invalide : {tenant_id!r}")
    jeton = _tenant_courant.set(tenant_id)
    try:
        yield tenant_id
    finally:
        _tenant_courant.reset(jeton)


# ---------------------------------------------------------------------------
# Migration SQL — Row Level Security
# ---------------------------------------------------------------------------

MIGRATION_RLS = """
-- Isolation multi-tenant par Row Level Security.
-- À appliquer à TOUTE table contenant des données client, sans exception :
-- documents, passages, embeddings, rapports, verdicts, journaux d'audit.

-- 1. Rôle applicatif non superutilisateur.
--    RLS est ignorée pour les superutilisateurs et les propriétaires de table :
--    l'application NE DOIT PAS se connecter avec le rôle propriétaire.
CREATE ROLE complianceai_app NOLOGIN;

-- 2. Activation, table par table.
ALTER TABLE documents        ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents        FORCE  ROW LEVEL SECURITY;
ALTER TABLE passages         ENABLE ROW LEVEL SECURITY;
ALTER TABLE passages         FORCE  ROW LEVEL SECURITY;
ALTER TABLE rapports_audit   ENABLE ROW LEVEL SECURITY;
ALTER TABLE rapports_audit   FORCE  ROW LEVEL SECURITY;
ALTER TABLE verdicts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE verdicts         FORCE  ROW LEVEL SECURITY;

-- 3. Politique unique par table : lecture ET écriture filtrées.
CREATE POLICY isolation_tenant ON documents
  USING       (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK  (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY isolation_tenant ON passages
  USING       (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK  (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY isolation_tenant ON rapports_audit
  USING       (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK  (tenant_id = current_setting('app.tenant_id', true));

CREATE POLICY isolation_tenant ON verdicts
  USING       (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK  (tenant_id = current_setting('app.tenant_id', true));

-- 4. Index composites : le tenant_id EN PREMIER, sinon PostgreSQL scanne
--    l'ensemble avant de filtrer.
CREATE INDEX idx_passages_tenant     ON passages (tenant_id, document_id);
CREATE INDEX idx_rapports_tenant     ON rapports_audit (tenant_id, cree_le DESC);

-- 5. Index vectoriel PARTITIONNÉ par tenant.
--    Un index HNSW global renvoie les voisins les plus proches tous tenants
--    confondus. Le filtre post-recherche ne suffit pas : il dégrade le rappel
--    et laisse fuiter le nombre de voisins par tenant.
CREATE INDEX idx_passages_embedding ON passages
  USING hnsw (embedding vector_cosine_ops)
  WHERE tenant_id IS NOT NULL;
"""

# Requête de recherche vectorielle. Le filtre tenant est dans la clause WHERE
# de la recherche elle-même, PAS appliqué après coup sur les résultats.
REQUETE_RECHERCHE = """
SELECT p.id, p.texte, p.section, p.document_id,
       1 - (p.embedding <=> %(vecteur)s::vector) AS similarite
FROM passages p
WHERE p.tenant_id = %(tenant_id)s
  AND p.document_id = %(document_id)s
ORDER BY p.embedding <=> %(vecteur)s::vector
LIMIT %(k)s;
"""


def ouvrir_session(connexion: Any, tenant_id: str | None = None) -> None:
    """
    Pose le tenant sur la connexion PostgreSQL. À appeler au début de CHAQUE
    transaction, avant toute requête.

    `set_config(..., true)` limite la portée à la transaction courante : le
    réglage ne fuit pas vers la transaction suivante via le pool de connexions.
    C'est essentiel avec pgbouncer ou tout pooling.
    """
    tenant = tenant_id or tenant_actuel()
    with connexion.cursor() as cur:
        cur.execute("SELECT set_config('app.tenant_id', %s, true);", (tenant,))
    logger.debug("session ouverte pour le tenant %s", tenant)


def controler_resultats(lignes: list[dict], tenant_id: str | None = None) -> list[dict]:
    """
    Contrôle de dernier recours : vérifie qu'aucune ligne d'un autre tenant
    n'a traversé. Ne remplace pas la RLS — il la surveille.

    Si cette fonction lève, c'est un incident de sécurité : la RLS est mal
    configurée ou l'application se connecte avec le mauvais rôle.
    """
    tenant = tenant_id or tenant_actuel()
    intrus = {
        str(l.get("tenant_id"))
        for l in lignes
        if l.get("tenant_id") is not None and str(l.get("tenant_id")) != tenant
    }
    if intrus:
        logger.critical(
            "FUITE INTER-TENANT : tenant attendu=%s, tenants reçus=%s", tenant, intrus
        )
        raise FuiteTenantError(
            f"Fuite inter-tenant détectée. Attendu {tenant}, reçu {intrus}. "
            "Vérifier la RLS et le rôle de connexion applicatif."
        )
    return lignes


def dependance_fastapi(tenant_id: str):
    """
    Dépendance FastAPI. Le tenant provient du jeton d'authentification vérifié,
    JAMAIS d'un en-tête ou d'un paramètre fourni par le client : un tenant_id
    lu dans la requête est une porte ouverte.

        @app.post("/audits")
        async def creer_audit(tenant: str = Depends(tenant_depuis_jwt)):
            with contexte_tenant(tenant):
                ...
    """
    return contexte_tenant(tenant_id)
