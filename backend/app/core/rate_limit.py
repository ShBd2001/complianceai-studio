"""Limitation de debit. Isole dans son module pour eviter les imports
circulaires entre main.py et les routeurs."""

from slowapi import Limiter
from slowapi.util import get_remote_address

from app.core.config import settings

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["200/minute"],
    enabled=settings.RATE_LIMIT_ENABLED,
)

# Limites renforcees sur les routes sensibles (anti bruteforce / anti spam).
LOGIN_LIMIT = "10/minute"
REGISTER_LIMIT = "5/hour"
PASSWORD_RESET_LIMIT = "5/hour"
RESEND_VERIFICATION_LIMIT = "5/hour"

# Le lancement d'une campagne appelle le modele de langage une fois par
# exigence auditable (voir audits.py::run_audit) : sans limite dediee, le
# defaut global (200/minute, voir Limiter ci-dessus) laisserait un seul
# client declencher des centaines d'executions couteuses en quelques
# minutes. Le quota de campagnes/mois (app/services/quotas.py) borne le
# nombre de campagnes crees, pas le nombre de fois qu'on relance l'analyse
# d'une meme campagne -- d'ou cette limite separee.
AUDIT_RUN_LIMIT = "20/hour"
