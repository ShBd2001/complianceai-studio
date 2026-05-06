"""Isolation des tests.

Les tests ecrivent en base, et certains reingerent un referentiel avec
`force=True`. S'ils tournaient sur la base de developpement, chaque execution
de la suite detruirait les referentiels reellement ingeres.

Ce module bascule donc la suite sur une base dediee, suffixee `_test`, creee
et migree automatiquement au premier lancement. Il s'execute avant tout import
applicatif : `pytest` charge conftest.py en premier, et la configuration lit
l'environnement en priorite sur le fichier .env.
"""

from __future__ import annotations

import os
import pathlib
from urllib.parse import urlsplit, urlunsplit

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[1]

os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ.setdefault("DEBUG", "false")
# La qualite semantique importe peu ici, la reproductibilite oui :
# le repli par hachage evite de dependre d'un modele telecharge.
os.environ.setdefault("EMBEDDING_BACKEND", "hashing")

# Le moteur est neutralise pour toute la suite, sans valeur par defaut
# surchargeable : plusieurs tests verifient le garde-fou qui retire le score
# quand l'analyse s'est faite sans modele, et ils supposaient jusqu'ici qu'aucune
# cle Groq n'etait configuree. Sur un poste qui en possede une, ils tournaient
# contre le fournisseur reel : la suite consommait du quota, dependait du reseau,
# et ces tests passaient a cote de ce qu'ils annoncaient verifier.
os.environ["LLM_ENABLED"] = "false"
os.environ["GROQ_API_KEY"] = ""


def _database_url_from_dotenv() -> str | None:
    env_file = BACKEND_ROOT / ".env"
    if not env_file.exists():
        return None
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("DATABASE_URL="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


def _test_url(url: str) -> str:
    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    if name.endswith("_test"):
        return url
    return urlunsplit(
        (parts.scheme, parts.netloc, f"/{name}_test", parts.query, parts.fragment)
    )


def _ensure_database(url: str) -> None:
    """Cree la base de test si elle n'existe pas encore."""
    import psycopg

    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    # psycopg attend une chaine libpq : le suffixe de pilote SQLAlchemy doit
    # etre retire, et on se connecte a `postgres` pour pouvoir creer la base.
    scheme = parts.scheme.split("+")[0]
    admin = urlunsplit((scheme, parts.netloc, "/postgres", parts.query, parts.fragment))

    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (name,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")


_source = os.environ.get("DATABASE_URL") or _database_url_from_dotenv()
if _source:
    _target = _test_url(_source)
    os.environ["DATABASE_URL"] = _target
    _ensure_database(_target)
    _migrate()
