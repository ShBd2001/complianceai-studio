"""Contrat commun a tous les connecteurs de referentiels."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

from app.models.enums import Pillar, RequirementKind


@dataclass(slots=True)
class RawRequirement:
    """Exigence extraite d'une source, avant normalisation en base."""

    reference: str
    title: str
    body: str
    kind: RequirementKind = RequirementKind.ARTICLE
    ordering: int = 0
    parent_reference: str | None = None
    source_url: str | None = None


@dataclass(slots=True)
class IngestionResult:
    code: str
    name: str
    pillar: Pillar
    authority: str
    source_url: str
    license: str
    celex_id: str | None = None
    version_label: str = "1.0"
    effective_date: date | None = None
    is_redistributable: bool = True
    requirements: list[RawRequirement] = field(default_factory=list)
    raw_text: str = ""

    @property
    def sha256(self) -> str:
        """Empreinte du texte source : socle du dispositif de veille."""
        return hashlib.sha256(self.raw_text.encode("utf-8")).hexdigest()


class Connector(ABC):
    """Un connecteur doit etre idempotent : deux executions successives sur une
    source inchangee produisent la meme empreinte et n'ecrivent rien."""

    code: str

    @abstractmethod
    def fetch(self) -> IngestionResult:
        """Recupere et analyse la source. Peut lever en cas d'indisponibilite."""
