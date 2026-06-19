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
