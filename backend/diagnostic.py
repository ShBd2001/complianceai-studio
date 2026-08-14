"""Diagnostic des briques externes : embeddings et modele de langage.

    python diagnostic.py

A lancer depuis le dossier backend, venv active.
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)-8s %(message)s")


def section(title: str) -> None:
    print(f"\n{'=' * 62}\n{title}\n{'=' * 62}")


def main() -> int:
    from app.core.config import settings

    section("CONFIGURATION")
    key = settings.GROQ_API_KEY or ""
    print(f"  GROQ_API_KEY       : {'oui, ' + key[:7] + '...' if key else 'ABSENTE'}")
    print(f"  GROQ_MODEL         : {settings.GROQ_MODEL}")
    print(f"  LLM_ENABLED        : {settings.LLM_ENABLED}")
    print(f"  LLM_MAX_CONCURRENCY: {settings.LLM_MAX_CONCURRENCY}")
    print(f"  EMBEDDING_BACKEND  : {settings.EMBEDDING_BACKEND}")
    print(f"  EMBEDDING_DIM      : {settings.EMBEDDING_DIM}")

    section("EMBEDDINGS")
    from app.services.embeddings import FastEmbedEmbedder, get_embedder

    embedder = get_embedder()
    name = type(embedder).__name__
    print(f"  Implementation reelle : {name} ({embedder.dimension} dimensions)")
    if not isinstance(embedder, FastEmbedEmbedder):
        print("  ATTENTION : repli par hachage actif.")
        print("  La recherche semantique ne fonctionne pas dans ce mode.")
    else:
        vector = embedder.embed_one("registre des activites de traitement")
        print(f"  Vecteur de test : {len(vector)} composantes, "
              f"premiere = {vector[0]:.4f}")

    section("MODELE DE LANGAGE")
    from app.services import llm

    print(f"  llm.is_available() : {llm.is_available()}")
    if not llm.is_available():
        print("  Cle absente ou LLM desactive : rien a tester.")
        return 1

    prompt_system = (
        "Tu es un auditeur. Tu reponds exclusivement en JSON valide, "
        "sans aucun texte autour."
    )
    prompt_user = (
        'Renvoie exactement cet objet : '
        '{"conforme": "oui", "confiance": 0.9, "severite": "info", '
        '"constat": "test", "preuve": null, "recommandation": "aucune"}'
    )

    print("  Appel en cours...")
    try:
        result = llm.complete_json(prompt_system, prompt_user, max_tokens=300)
    except Exception as exc:
        print(f"\n  ECHEC : {type(exc).__name__}")
        print(f"  {exc}")
        print("\n  Causes frequentes :")
        print("    - cle invalide ou revoquee")
        print("    - nom de modele inexistant (verifier GROQ_MODEL)")
        print("    - quota depasse")
        print("    - proxy d'entreprise bloquant api.groq.com")
        return 1

    print(f"  SUCCES. Reponse : {result}")

    section("RESULTAT")
    print("  Les deux briques repondent. Un audit lance maintenant utilisera")
    print("  reellement le modele, a condition qu'uvicorn ait ete redemarre")
    print("  APRES la derniere modification du fichier .env.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
