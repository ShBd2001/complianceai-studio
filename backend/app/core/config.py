from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator


class Settings(BaseSettings):
    """Configuration centralisee, chargee depuis l'environnement (12-factor)."""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    APP_NAME: str = "ComplianceAI Studio"
    ENV: str = "development"
    DEBUG: bool = False

    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def _force_psycopg_driver(cls, v: str) -> str:
        """Impose le driver psycopg (v3), quel que soit le schema fourni.

        Les URL generees automatiquement par un hebergeur (ex. Render,
        Heroku : `postgresql://...` ou `postgres://...`) ne precisent pas de
        driver. SQLAlchemy retombe alors sur psycopg2, jamais installe ici
        (le projet standardise sur psycopg v3) — l'echec (`ModuleNotFoundError`)
        ne se voit qu'au moment de se connecter, en production.
        """
        if v.startswith("postgres://"):
            v = "postgresql://" + v[len("postgres://"):]
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    JWT_SECRET: str
    JWT_ALG: str = "HS256"
    ACCESS_TOKEN_TTL_MIN: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 14

    COOKIE_SECURE: bool = True
    COOKIE_DOMAIN: str | None = None
    REFRESH_COOKIE_NAME: str = "cai_refresh"

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    RATE_LIMIT_ENABLED: bool = True

    # Origine servant a construire les liens absolus dans les e-mails
    # (verification, reinitialisation) : une adresse relative n'a pas de sens
    # hors du contexte d'une page deja ouverte.
    FRONTEND_URL: str = "http://localhost:5173"

    # --- E-mail transactionnel ---
    # Ordre de priorite : Brevo (API HTTP) > SMTP > fichier local.
    #
    # Les plans gratuits des hebergeurs (Render compris) bloquent couramment
    # les ports SMTP sortants (25/465/587) pour lutter contre le spam — le
    # SMTP peut donc fonctionner en local et echouer silencieusement en
    # production, sans rapport avec les identifiants. Brevo (ou tout
    # fournisseur a API HTTP) contourne ca : le trafic passe en HTTPS,
    # jamais bloque.
    BREVO_API_KEY: str | None = None
    EMAIL_FROM: str | None = None
    EMAIL_FROM_NAME: str = "ComplianceAI Studio"

    # SMTP_HOST vide (defaut) : aucun envoi reseau, le message est ecrit dans
    # STORAGE_DIR/emails/ pour rester testable sans fournisseur configure.
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False

    GROQ_API_KEY: str | None = None
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    # Temperature de l'evaluation. Zero pour maximiser la reproductibilite :
    # un audit doit rendre le meme verdict sur le meme document. La
    # determination reste imparfaite — l'inference GPU n'est pas stable au bit
    # pres — d'ou la mesure de variance dans validation/evaluate.py.
    LLM_TEMPERATURE: float = 0.0
    LLM_ENABLED: bool = True
    # Appels au modele menes de front pendant un audit.
    LLM_MAX_CONCURRENCY: int = 3
    # Duree maximale d'un audit. Au-dela, on rend la main avec ce qui a ete
    # evalue plutot que de laisser une requete HTTP pendre indefiniment.
    AUDIT_MAX_SECONDS: int = 240
    # Nombre d'echecs consecutifs de limitation avant d'arreter de solliciter
    # le fournisseur pour le reste de l'audit.
    LLM_BREAKER_THRESHOLD: int = 3

    # 384 = dimension de intfloat/multilingual-e5-small.
    # Toute modification impose une migration de la colonne vector.
    EMBEDDING_DIM: int = 384
    EMBEDDING_BACKEND: str = "fastembed"  # "fastembed" | "hashing"

    STORAGE_DIR: str = "./storage"
    MAX_UPLOAD_MB: int = 20
    RAG_TOP_K: int = 3

    # Bornes de taille du prompt d'evaluation, en caracteres.
    # Determinantes face a un fournisseur qui limite les jetons par minute :
    # diviser la taille du prompt par deux double le nombre d'evaluations
    # possibles dans la meme fenetre.
    PROMPT_REQUIREMENT_CHARS: int = 1500
    PROMPT_PASSAGE_CHARS: int = 600

    # Conservation des donnees (RGPD art. 5.1.e)
    ACTIVITY_LOG_RETENTION_DAYS: int = 365
    ACCOUNT_PURGE_GRACE_DAYS: int = 30

    # Boucle de planification in-process (veille reglementaire, campagnes
    # recurrentes). Desactivee par defaut : elle interroge EUR-Lex (throttle
    # connu des clients automatises) et, pour les campagnes recurrentes,
    # depense du quota Groq sans supervision humaine. A activer sciemment.
    SCHEDULER_ENABLED: bool = False
    SCHEDULER_POLL_SECONDS: int = 300
    REGULATORY_WATCH_INTERVAL_HOURS: int = 24

    @property
    def is_production(self) -> bool:
        return self.ENV.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
