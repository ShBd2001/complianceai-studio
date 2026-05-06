import enum


class OrgRole(str, enum.Enum):
    """Roles au sein d'une organisation (RBAC, ref. CC1.2)."""

    OWNER = "owner"        # tout, y compris suppression de l'organisation
    ADMIN = "admin"        # gestion des membres et des audits
    AUDITOR = "auditor"    # cree et modifie des audits
    VIEWER = "viewer"      # lecture seule

    @property
    def level(self) -> int:
        return {"viewer": 0, "auditor": 1, "admin": 2, "owner": 3}[self.value]


class Framework(str, enum.Enum):
    """Codes de referentiels supportes.

    ISO 27001 est volontairement absente : son texte est sous copyright AFNOR
    et sa redistribution est interdite. Elle est remplacee par NIST CSF 2.0
    (domaine public) et le guide d'hygiene ANSSI (Licence Ouverte).
    """

    RGPD = "rgpd"
    NIS2 = "nis2"
    AI_ACT = "ai_act"
    DORA = "dora"
    # Directive modificative : la plupart de ses articles amendent la
    # directive comptable 2013/34/UE sans creer d'obligation directement
    # opposable. Seuls les articles inseres (suffixes bis/ter/...) portent de
    # vraies obligations de publication et sont marques auditables — voir
    # app/ingestion/scoping.py::classify. La granularite ESRS elle-meme n'est
    # pas ingeree : le perimetre couvert est l'obligation de publier, pas le
    # contenu detaille du rapport de durabilite.
    CSRD = "csrd"
    NIST_CSF = "nist_csf"
    ANSSI = "anssi"


class AuditStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"


class Severity(str, enum.Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class FindingStatus(str, enum.Enum):
    OPEN = "open"
    NOT_APPLICABLE = "not_applicable"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    ACCEPTED_RISK = "accepted_risk"
    FALSE_POSITIVE = "false_positive"


class ConsentPurpose(str, enum.Enum):
    TOS = "terms_of_service"
    DOCUMENT_PROCESSING = "document_processing"
    MARKETING_EMAILS = "marketing_emails"


class Pillar(str, enum.Enum):
    """Domaines couverts par les referentiels."""

    PRIVACY = "privacy"           # RGPD, Loi Informatique et Libertes
    CYBERSECURITY = "cybersecurity"  # NIS2, NIST CSF, ANSSI
    SUSTAINABILITY = "sustainability"  # CSRD, ESRS
    AI_GOVERNANCE = "ai_governance"  # Reglement (UE) 2024/1689 sur l'IA
    OPERATIONAL_RESILIENCE = "operational_resilience"  # DORA, reglement (UE) 2022/2554


class RequirementKind(str, enum.Enum):
    CHAPTER = "chapter"
    SECTION = "section"
    ARTICLE = "article"
    PARAGRAPH = "paragraph"
    MEASURE = "measure"


class ScheduleCadence(str, enum.Enum):
    """Cadence approximative d'une campagne d'audit recurrente (pas de cron
    complet : trois pas fixes suffisent a l'usage vise)."""

    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
