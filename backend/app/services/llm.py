"""Client LLM (Groq) avec sortie JSON contrainte et repli deterministe.

Le repli n'est pas un artifice de demonstration : il garantit qu'une panne du
fournisseur ou l'absence de cle n'empeche pas l'application de fonctionner, et
il rend les tests reproductibles sans appel reseau.
"""

from __future__ import annotations

import json
import logging
import random
import re
import time
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class LLMUnavailable(RuntimeError):
    pass


class LLMRateLimited(LLMUnavailable):
    pass


# Un audit emet des dizaines d'appels rapproches. Les paliers gratuits
# limitent le debit et repondent 429 : sans reessai, chaque appel echoue et
# l'audit bascule entierement sur l'heuristique.
MAX_ATTEMPTS = 3
BASE_BACKOFF = 1.5
# Plafond d'attente par tentative. Groq annonce parfois des delais de plusieurs
# dizaines de secondes : les respecter integralement, multiplie par le nombre
# d'exigences, ferait durer un audit plus d'une heure. Mieux vaut abandonner
# l'appel et laisser le disjoncteur decider.
MAX_BACKOFF = 8.0


def is_available() -> bool:
    return bool(settings.LLM_ENABLED and settings.GROQ_API_KEY)


def _extract_json(text: str) -> Any:
    """Isole le JSON meme si le modele l'a entoure de texte ou de balises."""
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    match = re.search(r"[\[{].*[\]}]", cleaned, re.DOTALL)
    if match is None:
        raise ValueError("Aucun JSON exploitable dans la reponse du modele.")
    return json.loads(match.group(0))


def complete_json(
    system_prompt: str,
    user_prompt: str,
    *,
    temperature: float | None = None,
    max_tokens: int = 2000,
    timeout: float = 90.0,
) -> Any:
    if not is_available():
        raise LLMUnavailable("GROQ_API_KEY absente ou LLM desactive.")

    payload = {
        "model": settings.GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": (
            settings.LLM_TEMPERATURE if temperature is None else temperature
        ),
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    headers = {"Authorization": f"Bearer {settings.GROQ_API_KEY}"}
    last_error: str = ""

    with httpx.Client(timeout=timeout) as client:
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = client.post(GROQ_URL, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                last_error = f"erreur reseau : {exc}"
                _sleep_before_retry(attempt, None)
                continue

            if response.status_code == 429 or response.status_code >= 500:
                # Le fournisseur indique parfois le delai a respecter.
                retry_after = response.headers.get("retry-after")
                last_error = f"HTTP {response.status_code}"
                if attempt == 1:
                    # Le corps precise quelle limite est atteinte (requetes par
                    # minute, jetons par minute, quota journalier) et le delai
                    # de reinitialisation. Sans cette trace, le diagnostic est
                    # impossible : un 429 seul ne dit pas laquelle.
                    logger.warning(
                        "Limitation du fournisseur : %s", response.text[:400]
                    )
                logger.warning(
                    "Groq %s (tentative %d/%d)", response.status_code, attempt, MAX_ATTEMPTS
                )
                if attempt < MAX_ATTEMPTS:
                    _sleep_before_retry(attempt, retry_after)
                    continue
                raise LLMRateLimited(
                    f"Groq a repondu {response.status_code} apres {MAX_ATTEMPTS} tentatives."
                )

            if response.status_code >= 400:
                # 400, 401, 404 : reessayer ne changerait rien.
                logger.error("Groq %s : %s", response.status_code, response.text[:400])
                raise LLMUnavailable(
                    f"Groq a repondu {response.status_code} : {response.text[:200]}"
                )

            content = response.json()["choices"][0]["message"]["content"]
            return _extract_json(content)

    raise LLMUnavailable(last_error or "Appel au modele impossible.")


def _sleep_before_retry(attempt: int, retry_after: str | None) -> None:
    """Attente exponentielle, avec une part aleatoire.

    Sans cette part, tous les workers d'un audit reessaieraient au meme
    instant et reprovoqueraient la limitation.
    """
    if retry_after:
        try:
            time.sleep(min(float(retry_after), MAX_BACKOFF))
            return
        except ValueError:
            pass
    time.sleep(min(BASE_BACKOFF ** attempt + random.uniform(0, 1), MAX_BACKOFF))
