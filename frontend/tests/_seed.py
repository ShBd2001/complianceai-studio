"""Ingere un referentiel RGPD factice dans la base E2E — memes donnees que
`backend/tests/test_audit_pipeline.py`, executees ici comme sous-processus
(le processus de test et le processus API sont deux interpretes distincts,
seule la base de donnees est partagee).
"""

from datetime import date

from app.db.session import SessionLocal
from app.ingestion.base import IngestionResult, RawRequirement
from app.ingestion.runner import ingest
from app.models.enums import Pillar, RequirementKind


class FakeConnector:
    code = "rgpd"

    def fetch(self) -> IngestionResult:
        articles = [
            ("Article 5", "Principes relatifs au traitement",
             "Les donnees a caractere personnel doivent etre traitees de maniere "
             "licite, loyale et transparente."),
            ("Article 30", "Registre des activites de traitement",
             "Chaque responsable du traitement tient un registre des activites de "
             "traitement effectuees sous sa responsabilite."),
            ("Article 32", "Securite du traitement",
             "Le responsable du traitement met en oeuvre les mesures techniques et "
             "organisationnelles appropriees, notamment le chiffrement des donnees."),
            ("Article 33", "Notification des violations",
             "En cas de violation de donnees a caractere personnel, le responsable "
             "du traitement notifie la violation a l'autorite de controle."),
        ]
        requirements = [
            RawRequirement(
                reference=ref, title=title, body=body,
                kind=RequirementKind.ARTICLE, ordering=i + 1,
                source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            )
            for i, (ref, title, body) in enumerate(articles)
        ]
        return IngestionResult(
            code="rgpd", name="Reglement general sur la protection des donnees",
            pillar=Pillar.PRIVACY, authority="Parlement europeen et Conseil",
            source_url="https://eur-lex.europa.eu/eli/reg/2016/679/oj",
            license="Decision 2011/833/UE", celex_id="32016R0679",
            version_label="2016/679", effective_date=date(2018, 5, 25),
            requirements=requirements,
            raw_text="\n".join(f"{r.reference} {r.title} {r.body}" for r in requirements),
        )


if __name__ == "__main__":
    with SessionLocal() as db:
        report = ingest(db, FakeConnector(), force=True)
        db.commit()
        print(f"Referentiel ingere : {report.status}, {report.requirements} exigences.")
