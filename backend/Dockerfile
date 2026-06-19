FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Chromium pour la generation des rapports en PDF (services/pdf.py).
# --with-deps installe aussi les bibliotheques systeme necessaires (fonts,
# libnss, etc.) : doit s'executer avant de passer a l'utilisateur non
# privilegie. PLAYWRIGHT_BROWSERS_PATH pointe vers un dossier partage, rendu
# accessible a appuser ci-dessous.
RUN playwright install --with-deps chromium

COPY . .

# Execution sans privileges (durcissement conteneur)
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app /ms-playwright
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://localhost:8000/health || exit 1

# --proxy-headers/--forwarded-allow-ips='*' : sans ca, request.client.host
# vaut l'adresse interne du proxy Render pour CHAQUE requete, quel que soit
# le visiteur reel. Consequence concrete constatee : le limiteur de debit
# anti-brute-force (slowapi, cle = adresse IP) partage alors un seul compteur
# entre tous les visiteurs du site au lieu d'un par personne — quelques
# tentatives de n'importe qui suffisent a bloquer tout le monde.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
