"""Infrastructure des tests bout-en-bout du frontend.

Pilote un vrai navigateur (Chrome installe sur la machine, via Playwright —
aucun telechargement de binaire supplementaire, `channel="chrome"` reutilise
l'installation existante) contre le vrai backend FastAPI et le vrai serveur
statique du frontend, tous deux demarres et arretes par cette session de
tests. Base Postgres dediee (`..._e2e`), creee et migree automatiquement,
jamais la base de developpement.

Le frontend determine l'adresse de l'API a partir du port sur lequel il est
servi (`frontend/index.html` : `API = location.port === '5173' ? ... `) —
cette suite doit donc utiliser les ports 8000 (API) et 5173 (frontend), les
memes qu'en developpement local. Consequence directe : ces tests ne peuvent
pas tourner en meme temps qu'un serveur de developpement deja lance sur ces
ports. Arreter les serveurs manuels avant de lancer cette suite.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
FRONTEND_ROOT = REPO_ROOT / "frontend"

API_PORT = 8000
FRONTEND_PORT = 5173
API_URL = f"http://localhost:{API_PORT}"
FRONTEND_URL = f"http://localhost:{FRONTEND_PORT}"


def _database_url_from_dotenv() -> str:
    env_file = BACKEND_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return "postgresql+psycopg://compliance:compliance@localhost:5432/complianceai"


def _e2e_database_url() -> str:
    parts = urlsplit(_database_url_from_dotenv())
    return urlunsplit((parts.scheme, parts.netloc, "/complianceai_e2e", parts.query, parts.fragment))


def _ensure_database(url: str) -> None:
    import psycopg

    parts = urlsplit(url)
    name = parts.path.lstrip("/")
    scheme = parts.scheme.split("+")[0]
    admin = urlunsplit((scheme, parts.netloc, "/postgres", parts.query, parts.fragment))
    with psycopg.connect(admin, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')


def _wait_for(url: str, *, timeout: float = 30.0) -> None:
    import httpx

    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            r = httpx.get(url, timeout=2.0)
            if r.status_code < 500:
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.3)
    raise RuntimeError(f"{url} n'a jamais repondu a temps ({last_error}).")


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


@pytest.fixture(scope="session")
def env_e2e() -> dict[str, str]:
    db_url = _e2e_database_url()
    _ensure_database(db_url)

    env = os.environ.copy()
    env.update({
        "DATABASE_URL": db_url,
        "JWT_SECRET": "e2e-only-secret-never-used-outside-this-suite-0123456789",
        "ENV": "development",
        "DEBUG": "false",
        "RATE_LIMIT_ENABLED": "false",
        "EMBEDDING_BACKEND": "hashing",
        "LLM_ENABLED": "false",
        "GROQ_API_KEY": "",
        "SCHEDULER_ENABLED": "false",
        "FRONTEND_URL": FRONTEND_URL,
        "CORS_ORIGINS": f'["{FRONTEND_URL}"]',
    })
    return env


@pytest.fixture(scope="session")
def storage_dir(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("e2e-storage")


@pytest.fixture(scope="session")
def backend_server(env_e2e, storage_dir):
    if not _port_free(API_PORT):
        pytest.fail(
            f"Le port {API_PORT} est deja occupe — arrete le serveur de "
            "developpement avant de lancer cette suite (voir docstring)."
        )

    env = dict(env_e2e)
    env["STORAGE_DIR"] = str(storage_dir)

    # Migre le schema de la base dediee avant de demarrer l'API.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_ROOT, env=env, check=True,
    )
    # Ingere un referentiel RGPD factice (memes donnees que la suite pytest
    # backend) : aucune dependance a EUR-Lex, deterministe.
    # PYTHONPATH est necessaire ici (contrairement a `-m uvicorn`/`-m alembic`
    # plus bas) : invoquer un script par chemin ajoute le dossier du script a
    # sys.path, pas le cwd, donc `app` ne serait pas importable sans elle.
    seed_env = dict(env)
    seed_env["PYTHONPATH"] = str(BACKEND_ROOT)
    subprocess.run(
        [sys.executable, str(Path(__file__).parent / "_seed.py")],
        cwd=BACKEND_ROOT, env=seed_env, check=True,
    )

    # stdout/stderr vers un fichier, jamais vers PIPE sans lecteur : un pipe
    # non lu se remplit (uvicorn logge chaque requete) et bloque le
    # sous-processus des que le tampon est plein — tous les tests suivant le
    # premier restaient alors bloques en attente d'une reponse qui ne venait
    # jamais.
    log_path = storage_dir / "uvicorn.log"
    log_file = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)],
        cwd=BACKEND_ROOT, env=env,
        stdout=log_file, stderr=subprocess.STDOUT, text=True,
    )
    try:
        _wait_for(f"{API_URL}/health")
        yield {"url": API_URL, "storage_dir": storage_dir}
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log_file.close()


@pytest.fixture(scope="session")
def frontend_server(backend_server):
    if not _port_free(FRONTEND_PORT):
        pytest.fail(
            f"Le port {FRONTEND_PORT} est deja occupe — arrete le serveur de "
            "developpement avant de lancer cette suite (voir docstring)."
        )

    proc = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(FRONTEND_PORT)],
        cwd=FRONTEND_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for(FRONTEND_URL)
        yield FRONTEND_URL
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser, frontend_server, request):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900})
    p = ctx.new_page()
    p.on("pageerror", lambda e: print(f"PAGEERROR: {e}"))
    yield p
    if getattr(request.node, "rep_call", None) is not None and request.node.rep_call.failed:
        Path("failures").mkdir(exist_ok=True)
        safe_name = request.node.name.replace("/", "_")
        p.screenshot(path=f"failures/{safe_name}.png")
        Path(f"failures/{safe_name}.html").write_text(p.content(), encoding="utf-8")
        print(f"Echec : capture dans failures/{safe_name}.png")
    ctx.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
