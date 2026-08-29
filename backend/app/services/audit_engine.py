"""Moteur d'audit : confronte les documents du client aux exigences du
referentiel et produit des non-conformites tracables.

Principe directeur : le modele ne repond jamais de memoire. Chaque evaluation
lui fournit le texte exact de l'exigence et les passages du document client.
Chaque non-conformite produite cite l'article dont elle decoule, le document
source et le modele utilise — sans quoi elle ne serait pas opposable.
"""

from __future__ import annotations

import logging
import uuid
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.audit import Audit, Document, DocumentChunk, Finding
from app.models.enums import AuditStatus, FindingStatus, Severity
from app.models.framework import Framework, FrameworkVersion, Requirement
from app.ingestion.scoping import dependency_of
from app.services import llm, rag
from app.services.documents import chunk_text, extract_text, read_document
from app.services.eligibilite import depuis_organisation, filtrer_exigences
from app.services.embeddings import get_embedder

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Tu es un auditeur de conformite reglementaire francais, rigoureux et factuel.

Regles absolues :
- Tu ne t'appuies QUE sur le texte de l'exigence et les extraits du client fournis.
- Si les extraits ne permettent pas de conclure, tu le dis explicitement.
- Tu n'inventes jamais de reference d'article ni de fait.
- Tu reponds exclusivement en JSON valide, sans commentaire autour.

Bareme de conformite :
- "oui"             : l'exigence est traitee de maniere satisfaisante.
- "partiel"         : l'essentiel est traite, un element secondaire manque.
- "non"             : l'exigence n'est pas traitee, ou de facon manifestement
                      insuffisante.
- "non_applicable"  : l'exigence ne concerne pas cette organisation au vu de
                      son activite telle qu'elle ressort des documents.
- "indetermine"     : les extraits ne permettent pas de se prononcer.

Sur la non-applicabilite. Un referentiel contient des obligations
conditionnelles. Une PME qui vend des pieces industrielles ne traite pas de
donnees de sante, ne prend pas de decision automatisee et n'a pas de code de
conduite sectoriel. Un auditeur ecrit alors "non applicable" et passe : il ne
recommande pas de rediger un code de conduite a une entreprise qui n'en a pas
besoin.

Reponds "non_applicable" quand l'exigence porte sur une situation absente des
documents ET que rien n'indique que l'organisation s'y trouve. Reponds "non"
uniquement si l'obligation s'applique et n'est pas satisfaite. En cas de doute
reel sur l'applicabilite, reponds "indetermine" : mieux vaut signaler une
verification a faire qu'affirmer un manquement inexistant.

Bareme de gravite, a appliquer strictement :
- "critical" : manquement exposant a une sanction immediate ou a un risque
               grave pour les personnes concernees.
- "major"    : obligation substantielle absente des documents.
- "minor"    : obligation traitee, mais un point de detail reste a completer
               ou a formaliser. N'utilise ce niveau QUE si l'essentiel est
               deja couvert.
- "info"     : simple observation, sans manquement.

Si l'exigence est satisfaite, reponds "oui" avec la gravite "info". Si elle ne
concerne pas l'organisation, reponds "non_applicable" avec la gravite "info" et
explique en une phrase pourquoi. Ne cherche pas a trouver un defaut a tout
prix : un audit credible valide ce qui est conforme et ecarte ce qui ne
s'applique pas.

Format de reponse attendu :
{
  "conforme": "oui" | "partiel" | "non" | "indetermine",
  "confiance": 0.0 a 1.0,
  "severite": "critical" | "major" | "minor" | "info",
  "constat": "ce qui a ete observe dans les documents, en 2 a 4 phrases",
  "preuve": "citation textuelle courte extraite des documents, ou null",
  "recommandation": "action corrective concrete et actionnable"
}"""

# Poids d'une exigence non satisfaite, selon la gravite du manquement.
#
# Le bareme initial (1.0 / 0.6 / 0.3 / 0.1) donnait a une remarque mineure la
# moitie du poids d'une non-conformite majeure. Sur un audit reel, 31 remarques
# mineures ecrasaient alors le score autant que 12 vrais manquements : une
# organisation dotee d'une politique honnete mais perfectible obtenait 22/100,
# la ou un cabinet l'aurait situee autour de 60. Le bareme ci-dessous separe
# nettement ce qui est un manquement de ce qui est un axe d'amelioration.
SEVERITY_WEIGHT = {
    Severity.CRITICAL: 1.00,
    Severity.MAJOR: 0.85,
    Severity.MINOR: 0.30,
    Severity.INFO: 0.05,
}

# Une couverture partielle penalise la moitie d'une absence totale.
PARTIAL_FACTOR = 0.5
# Une exigence sur laquelle le modele ne peut pas conclure n'est ni validee ni
# sanctionnee : elle pese peu, mais pas zero, car l'absence de preuve
# exploitable est en soi un signal.
UNDETERMINED_PENALTY = 0.20

# Au-dela de cette gravite, il s'agit d'une non-conformite. En deca, d'un axe
# d'amelioration. La distinction change la lecture d'un rapport : 12 non-
# conformites et 31 ameliorations est actionnable, 45 non-conformites ne l'est
# pas.
NON_CONFORMITY_SEVERITIES = frozenset({Severity.CRITICAL, Severity.MAJOR})

# Verdict d'exigence hors perimetre de l'organisation auditee.
NOT_APPLICABLE = "non_applicable"


# Au-dela de cette proportion d'evaluations retombees sur l'heuristique, le
# resultat n'a plus de valeur d'audit : le score est retire plutot que publie.
DEGRADED_THRESHOLD = 0.30


@dataclass(slots=True)
class AuditOutcome:
    audit_id: uuid.UUID
    status: AuditStatus
    score: float | None
    findings: int
    evaluated: int
    message: str | None = None
    degraded: bool = False
    fallbacks: int = 0
    not_applicable: int = 0


# --------------------------------------------------------------------------
# Indexation des documents deposes
# --------------------------------------------------------------------------
def index_document(db: Session, document: Document) -> int:
    """Extrait, decoupe et vectorise un document. Retourne le nombre de fragments."""
    content = read_document(document.storage_key)
    text = extract_text(content, document.mime_type)
    fragments = chunk_text(text)

    if not fragments:
        logger.warning("Document %s : aucun texte exploitable.", document.filename)
        return 0

    db.query(DocumentChunk).filter(DocumentChunk.document_id == document.id).delete()

    rows = [
        DocumentChunk(
            document_id=document.id,
            organization_id=document.organization_id,
            chunk_index=i,
            content=fragment,
            meta={"filename": document.filename},
        )
        for i, fragment in enumerate(fragments)
    ]
    db.add_all(rows)
    db.flush()

    vectors = get_embedder().embed([r.content for r in rows])
    for row, vector in zip(rows, vectors, strict=True):
        row.embedding = vector
    db.flush()

    logger.info("Document %s indexe : %d fragments.", document.filename, len(rows))
    return len(rows)


# --------------------------------------------------------------------------
# Evaluation d'une exigence
# --------------------------------------------------------------------------
SOURCE_LLM = "llm"
SOURCE_HEURISTIC = "heuristique"
# Exclusion prononcee en amont par le filtre d'eligibilite, sans appel au
# modele. Distinguee des deux autres sources pour que le rapport puisse
# separer ce qui releve d'une regle de droit deterministe de ce qui releve
# d'une appreciation.
SOURCE_ELIGIBILITY = "filtre_eligibilite"


class Breaker:
    """Disjoncteur sur le fournisseur de modele.

    Apres plusieurs echecs consecutifs de limitation de debit, insister
    n'apporte rien : le quota est atteint et chaque tentative supplementaire
    ne fait qu'allonger l'audit. On ouvre alors le circuit et le reste des
    exigences bascule immediatement sur l'heuristique.
    """

    def __init__(self, threshold: int) -> None:
        self.threshold = threshold
        self._consecutive = 0
        self._open = False
        self._lock = threading.Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._open

    def record_failure(self) -> None:
        with self._lock:
            self._consecutive += 1
            if self._consecutive >= self.threshold and not self._open:
                self._open = True
                logger.warning(
                    "Disjoncteur ouvert apres %d echecs consecutifs : le reste "
                    "de l'audit sera evalue sans modele.", self._consecutive,
                )

    def record_success(self) -> None:
        with self._lock:
            self._consecutive = 0


def _heuristic_evaluation(requirement: Requirement, passages: list[rag.Passage]) -> dict:
    """Evaluation sans LLM : lexicale et prudente.

    Elle ne pretend pas remplacer l'analyse du modele. Elle permet a la chaine
    complete de fonctionner et d'etre testee sans appel reseau, et elle sert de
    filet en cas d'indisponibilite du fournisseur.
    """
    if not passages:
        return {
            "_source": SOURCE_HEURISTIC,
            "_passage_verifie": None,
            "conforme": "non",
            "confiance": 0.4,
            "severite": "major",
            "constat": "Aucun element documentaire ne traite de cette exigence.",
            "preuve": None,
            "recommandation": (
                f"Produire et verser une documentation couvrant {requirement.reference}."
            ),
        }

    best = min(p.distance for p in passages)
    if best < 0.25:
        verdict, severity, confidence = "oui", "info", 0.6
        constat = "Des elements documentaires traitent directement de cette exigence."
    elif best < 0.45:
        verdict, severity, confidence = "partiel", "minor", 0.5
        constat = "Des elements connexes existent mais la couverture parait incomplete."
    else:
        verdict, severity, confidence = "non", "major", 0.45
        constat = "Aucun element documentaire ne couvre suffisamment cette exigence."

    return {
        "_source": SOURCE_HEURISTIC,
        # Preuve deja verbatim par construction (tranche brute du passage) :
        # pas besoin de la revalider comme pour la sortie du modele.
        "_passage_verifie": passages[0],
        "conforme": verdict,
        "confiance": confidence,
        "severite": severity,
        "constat": constat,
        "preuve": passages[0].text[:300],
        "recommandation": (
            f"Completer la documentation relative a {requirement.reference} "
            f"({requirement.title})."
        ),
    }


def _passage_correspondant(preuve: str | None, passages: list[rag.Passage]) -> rag.Passage | None:
    """Retrouve, parmi les passages fournis au modele, celui qui contient
    reellement la citation qu'il avance — plutot que de faire confiance a son
    auto-declaration.

    C'est le controle qui rend la citation opposable (voir docstring du
    module) : sans lui, "preuve" n'est qu'un champ que le modele remplit sur
    parole, jamais verifie contre le texte source. Normalise les espaces pour
    tolerer une remise en forme mineure (retours a la ligne, espaces
    multiples) mais exige une correspondance verbatim du reste, et une
    longueur minimale — une citation de quelques mots ne prouve rien et
    correspondrait presque toujours par hasard.
    """
    if not preuve:
        return None
    cible = " ".join(preuve.split()).lower()
    if len(cible) < 15:
        return None
    for passage in passages:
        if cible in " ".join(passage.text.split()).lower():
            return passage
    return None


def evaluate_requirement(
    requirement: Requirement,
    passages: list[rag.Passage],
    breaker: Breaker | None = None,
) -> dict:
    """Evalue une exigence a partir de passages deja recuperes.

    Fonction pure vis-a-vis de la base : elle ne touche pas a la session, ce
    qui la rend appelable depuis un pool de threads.
    """
    if not llm.is_available() or (breaker is not None and breaker.is_open):
        return _heuristic_evaluation(requirement, passages)

    excerpts = "\n\n".join(
        f"[Extrait {i + 1} — {p.reference}]\n{p.text[: settings.PROMPT_PASSAGE_CHARS]}"
        for i, p in enumerate(passages)
    ) or "(aucun extrait pertinent trouve dans les documents deposes)"

    user_prompt = (
        f"EXIGENCE — {requirement.reference} : {requirement.title}\n"
        f"{requirement.body[: settings.PROMPT_REQUIREMENT_CHARS]}\n\n"
        f"EXTRAITS DES DOCUMENTS DU CLIENT :\n{excerpts}\n\n"
        f"Evalue la conformite du client a cette exigence."
    )

    try:
        verdict = llm.complete_json(SYSTEM_PROMPT, user_prompt)
        verdict["_source"] = SOURCE_LLM

        # Le modele ne repond jamais de memoire (voir docstring du module) :
        # une citation qu'on ne retrouve pas telle quelle dans les extraits
        # fournis n'est pas une preuve, c'est une affirmation. On ne publie
        # jamais une conformite ("oui"/"partiel") fondee sur une citation
        # invérifiee ou absente — y compris quand aucun passage pertinent
        # n'a ete retrouve, auquel cas aucune citation n'est de toute facon
        # verifiable. Le verdict est alors ramene a "indetermine" : ni
        # valide ni sanctionne, mais signale pour verification humaine
        # plutot que presente comme un constat de conformite.
        passage_verifie = _passage_correspondant(verdict.get("preuve"), passages)
        verdict["_passage_verifie"] = passage_verifie
        if str(verdict.get("conforme", "")).lower() in ("oui", "partiel") and passage_verifie is None:
            logger.info(
                "Citation non verifiee sur %s : conformite '%s' ramenee a "
                "'indetermine' par prudence.",
                requirement.reference, verdict.get("conforme"),
            )
            verdict["conforme"] = "indetermine"
            verdict["confiance"] = min(float(verdict.get("confiance") or 0.5), 0.3)
            verdict["constat"] = (
                "Le modele indiquait une conformite mais la citation fournie n'a "
                "pas pu etre retrouvee telle quelle dans les documents verses : "
                "verdict ramene a indetermine par prudence, une verification "
                "manuelle est necessaire. " + str(verdict.get("constat") or "")
            ).strip()

        if breaker is not None:
            breaker.record_success()
        return verdict
    except Exception as exc:
        logger.warning(
            "LLM indisponible sur %s (%s), repli heuristique.", requirement.reference, exc
        )
        if breaker is not None:
            breaker.record_failure()
        return _heuristic_evaluation(requirement, passages)


def _evaluate_all(
    retrieved: list[tuple[Requirement, list[rag.Passage]]],
    deadline: float | None = None,
) -> list[dict]:
    """Evalue toutes les exigences, sous disjoncteur et sous echeance.

    Deux garde-fous, appris a l'usage : sans eux, un fournisseur qui limite
    fortement le debit peut faire durer un audit plus d'une heure, sans que
    l'appelant puisse rien faire.
    """
    if not llm.is_available():
        return [evaluate_requirement(req, passages) for req, passages in retrieved]

    breaker = Breaker(settings.LLM_BREAKER_THRESHOLD)

    def evaluate(pair: tuple[Requirement, list[rag.Passage]]) -> dict:
        requirement, passages = pair
        if deadline is not None and time.monotonic() > deadline:
            return _heuristic_evaluation(requirement, passages)
        return evaluate_requirement(requirement, passages, breaker)

    workers = min(settings.LLM_MAX_CONCURRENCY, max(1, len(retrieved)))
    logger.info("Evaluation de %d exigences sur %d workers.", len(retrieved), workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        # map preserve l'ordre d'entree : les verdicts restent alignes sur les
        # exigences, ce dont depend le zip(..., strict=True) en aval.
        return list(pool.map(evaluate, retrieved))


# --------------------------------------------------------------------------
# Execution d'une campagne
# --------------------------------------------------------------------------
def _propagate_dependencies(
    framework_code: str,
    requirements: list[Requirement],
    verdicts: list[dict],
) -> int:
    """Ecarte les exigences dont l'article maitre est hors perimetre.

    Le modele evalue chaque exigence isolement : il ne peut pas savoir que
    les missions du delegue (art. 39) n'ont pas lieu d'etre si sa designation
    (art. 37) n'est pas obligatoire. Sans cette passe, le rapport affirme
    simultanement que le delegue n'est pas requis et que ses missions ne sont
    pas documentees.

    Les exclusions prononcees par le filtre d'eligibilite alimentent la meme
    cascade que celles decidees par le modele : c'est la raison pour laquelle
    leurs verdicts sont reinjectes dans la liste avant cet appel, plutot que
    traites a part.

    Retourne le nombre d'exigences reclassees.
    """
    excluded = {
        _article_number_of(requirement.reference)
        for requirement, verdict in zip(requirements, verdicts, strict=True)
        if str(verdict.get("conforme", "")).lower() == NOT_APPLICABLE
    }
    excluded.discard(None)

    reclassified = 0
    for requirement, verdict in zip(requirements, verdicts, strict=True):
        if str(verdict.get("conforme", "")).lower() == NOT_APPLICABLE:
            continue

        master = dependency_of(framework_code, requirement.reference)
        if master is None or master not in excluded:
            continue

        verdict["conforme"] = NOT_APPLICABLE
        verdict["severite"] = "info"
        verdict["recommandation"] = None
        verdict["constat"] = (
            f"Sans objet : cette exigence decoule de l'article {master}, "
            f"lui-meme hors perimetre pour cette organisation."
        )
        reclassified += 1

    if reclassified:
        logger.info(
            "%d exigence(s) ecartee(s) par dependance a un article hors perimetre.",
            reclassified,
        )
    return reclassified


def _article_number_of(reference: str) -> int | None:
    import re

    match = re.search(r"Article\s+(\d+)", reference, re.IGNORECASE)
    return int(match.group(1)) if match else None


def _to_severity(value: str | None) -> Severity:
    try:
        return Severity(str(value).lower())
    except ValueError:
        return Severity.MAJOR


def _model_label(verdict: dict) -> str:
    """Origine du verdict, telle qu'inscrite au rapport.

    Trois valeurs possibles : le nom du modele, l'heuristique lexicale, ou le
    filtre d'eligibilite. Un lecteur du rapport doit pouvoir distinguer une
    exclusion fondee sur une regle de droit d'une appreciation du modele.
    """
    source = verdict.get("_source")
    if source == SOURCE_LLM:
        return settings.GROQ_MODEL
    return str(source or SOURCE_HEURISTIC)


def run_audit(
    db: Session, audit: Audit, max_requirements: int | None = None
) -> AuditOutcome:
    """Execute la campagne : indexe les documents puis evalue les exigences.

    Le perimetre est celui des exigences marquees auditables a l'ingestion :
    les articles adresses aux Etats membres ou aux autorites de controle en
    sont exclus. Sur le RGPD, cela ramene 99 articles a 45 obligations
    reellement opposables a une organisation — sans jamais ecarter les
    articles 30 et 32, que decoupait la borne arbitraire precedente.

    Un second filtre, tenant au profil de l'organisation et non au contenu
    documentaire, ecarte en amont les obligations conditionnelles qui ne la
    concernent pas (registre, delegue, information en cas de collecte
    indirecte). Ces exclusions ne passent ni par la recherche ni par le
    modele : elles decoulent du texte reglementaire lui-meme.

    `max_requirements` reste disponible pour reduire volontairement le
    perimetre, par exemple lors d'une demonstration.
    """
    audit.status = AuditStatus.RUNNING
    audit.started_at = datetime.now(timezone.utc)
    audit.error_message = None
    db.flush()

    try:
        documents = list(db.scalars(select(Document).where(Document.audit_id == audit.id)))
        if not documents:
            raise ValueError("Aucun document n'a ete depose pour cet audit.")

        for document in documents:
            index_document(db, document)

        version = db.scalar(
            select(FrameworkVersion)
            .join(Framework, FrameworkVersion.framework_id == Framework.id)
            .where(
                Framework.code == audit.framework.value,
                FrameworkVersion.is_current.is_(True),
            )
        )
        if version is None:
            raise ValueError(
                f"Le referentiel '{audit.framework.value}' n'a pas encore ete ingere. "
                f"Lancer : python -m app.ingestion.cli --only {audit.framework.value}"
            )

        stmt = (
            select(Requirement)
            .where(
                Requirement.version_id == version.id,
                Requirement.is_auditable.is_(True),
            )
            .order_by(Requirement.ordering)
        )
        if max_requirements is not None:
            stmt = stmt.limit(max_requirements)

        requirements = list(db.scalars(stmt))
        if not requirements:
            raise ValueError(
                f"Aucune exigence auditable pour '{audit.framework.value}'. "
                f"Reingerer le referentiel : "
                f"python -m app.ingestion.cli --only {audit.framework.value} --force"
            )

        db.query(Finding).filter(Finding.audit_id == audit.id).delete()

        # Phase 0 : filtre d'eligibilite.
        #
        # Certaines obligations dependent du profil de l'organisme (effectif,
        # secteur, nature des donnees traitees) et non du contenu des documents.
        # Le modele ne peut pas les trancher : l'information ne figure dans aucun
        # passage. Sur le corpus de validation, les articles 30, 37 et 13
        # representaient 13 des 17 faux positifs pour cette seule raison.
        #
        # Les exigences ecartees recoivent directement un verdict
        # "non_applicable" : elles ne passent ni par la recherche ni par le
        # modele, ce qui supprime autant d'appels reseau, mais leur verdict est
        # reinjecte dans la liste complete afin que la propagation des
        # dependances et le calcul du score continuent de travailler sur
        # l'integralite du perimetre.
        profil = depuis_organisation(audit.organization)
        a_evaluer, exemptees = filtrer_exigences(
            requirements, audit.framework.value, profil, _article_number_of
        )

        verdicts_par_exigence: dict[uuid.UUID, dict] = {
            requirement.id: {
                "_source": SOURCE_ELIGIBILITY,
                "conforme": NOT_APPLICABLE,
                "confiance": 1.0,
                "severite": "info",
                "constat": f"{decision.justification} Fondement : {decision.reference}.",
                "preuve": None,
                "recommandation": None,
            }
            for requirement, decision in exemptees
        }

        if exemptees:
            logger.info(
                "Filtre d'eligibilite : %d exigence(s) hors perimetre (%s).",
                len(exemptees),
                ", ".join(requirement.reference for requirement, _ in exemptees),
            )

        # Phase 1 (base, sequentielle) : recuperer les passages pertinents.
        # La session SQLAlchemy n'est pas partageable entre threads, on isole
        # donc tous les acces base avant la parallelisation.
        retrieved: list[tuple[Requirement, list[rag.Passage]]] = [
            (
                requirement,
                rag.search_client_documents(
                    db,
                    f"{requirement.title} {requirement.body[:300]}",
                    organization_id=audit.organization_id,
                    audit_id=audit.id,
                ),
            )
            for requirement in a_evaluer
        ]

        # Phase 2 (reseau, parallele) : les appels au modele sont des I/O pures
        # et independants. Les paralleliser divise la duree d'un audit RGPD
        # complet par un facteur proche du nombre de workers.
        deadline = time.monotonic() + settings.AUDIT_MAX_SECONDS
        verdicts_evalues = _evaluate_all(retrieved, deadline=deadline)

        # Recomposition dans l'ordre d'origine : `verdicts` recouvre a nouveau
        # l'integralite de `requirements`, ce dont dependent les
        # zip(..., strict=True) en aval.
        for requirement, verdict in zip(a_evaluer, verdicts_evalues, strict=True):
            verdicts_par_exigence[requirement.id] = verdict
        verdicts = [verdicts_par_exigence[requirement.id] for requirement in requirements]

        # Coherence du rapport : une exigence conditionnee par un article
        # ecarte doit l'etre aussi.
        _propagate_dependencies(audit.framework.value, requirements, verdicts)

        # Phase 3 (base, sequentielle) : ecriture des constats.
        findings: list[Finding] = []
        penalty = 0.0
        total_weight = 0.0

        not_applicable = 0

        for requirement, verdict in zip(requirements, verdicts, strict=True):
            conformity = str(verdict.get("conforme", "indetermine")).lower()
            severity = _to_severity(verdict.get("severite"))
            weight = SEVERITY_WEIGHT[severity]

            # Une exigence non applicable sort du calcul, numerateur comme
            # denominateur. Noter une entreprise sur des obligations qui ne la
            # concernent pas fausse le score et decredibilise le rapport.
            if conformity == NOT_APPLICABLE:
                not_applicable += 1
                # Conserve comme trace d'audit : l'exclusion doit etre
                # justifiee et verifiable, pas silencieuse.
                findings.append(
                    Finding(
                        audit_id=audit.id,
                        article_ref=requirement.reference,
                        title=f"{requirement.reference} — {requirement.title}"[:300],
                        description=str(verdict.get("constat", ""))[:4000],
                        recommendation=None,
                        evidence=None,
                        severity=Severity.INFO,
                        status=FindingStatus.NOT_APPLICABLE,
                        model_used=_model_label(verdict),
                        confidence=float(verdict.get("confiance") or 0.0),
                        source_document_id=None,
                    )
                )
                continue

            # Chaque exigence applicable pese 1 dans le denominateur : le score
            # exprime la part du referentiel reellement couverte, ce qui se lit
            # et se defend, contrairement a une somme de poids variables.
            total_weight += 1.0

            if conformity == "oui":
                continue
            if conformity == "partiel":
                penalty += weight * PARTIAL_FACTOR
            elif conformity == "indetermine":
                penalty += UNDETERMINED_PENALTY
            else:
                penalty += weight

            # Le document source est celui du passage effectivement verifie
            # pour cette citation, pas systematiquement le premier depose :
            # sur un audit a plusieurs documents, l'ancien comportement
            # attribuait toute preuve au premier fichier quel que soit celui
            # dont elle provenait reellement.
            passage_verifie = verdict.get("_passage_verifie")
            if passage_verifie is not None and passage_verifie.document_id is not None:
                source_id = passage_verifie.document_id
            elif documents:
                source_id = documents[0].id
            else:
                source_id = None

            findings.append(
                Finding(
                    audit_id=audit.id,
                    article_ref=requirement.reference,
                    title=f"{requirement.reference} — {requirement.title}"[:300],
                    description=str(verdict.get("constat", ""))[:4000],
                    recommendation=str(verdict.get("recommandation") or "")[:4000] or None,
                    evidence=(str(verdict["preuve"])[:4000] if verdict.get("preuve") else None),
                    severity=severity,
                    status=FindingStatus.OPEN,
                    model_used=_model_label(verdict),
                    confidence=float(verdict.get("confiance") or 0.0),
                    source_document_id=source_id,
                )
            )

        db.add_all(findings)

        score = 100.0 if total_weight == 0 else max(
            0.0, round(100.0 * (1 - penalty / total_weight), 1)
        )

        # Un outil d'audit qui publie un score sans signaler qu'il a travaille
        # en mode degrade est plus dangereux qu'un outil qui ne repond pas :
        # le client prendrait le chiffre pour argent comptant.
        #
        # Le taux se calcule sur les seules exigences reellement soumises au
        # modele. Inclure les exclusions deterministes au denominateur ferait
        # franchir le seuil sur un petit organisme — ou le filtre ecarte
        # legitimement plusieurs obligations — et supprimerait un score valide.
        fallbacks = sum(1 for v in verdicts_evalues if v.get("_source") != SOURCE_LLM)
        ratio = fallbacks / len(verdicts_evalues) if verdicts_evalues else 0.0
        degraded = llm.is_available() and ratio > DEGRADED_THRESHOLD
        warning = None

        if degraded:
            warning = (
                f"Analyse degradee : {fallbacks} evaluations sur {len(verdicts_evalues)} "
                f"n'ont pas pu etre traitees par le modele et sont retombees sur "
                f"l'heuristique lexicale. Le score n'est pas publie car il ne "
                f"serait pas representatif. Verifier la disponibilite du "
                f"fournisseur, puis relancer l'analyse."
            )
            logger.warning(warning)
            score = None
        elif not llm.is_available():
            warning = (
                "Analyse realisee sans modele de langage : les constats "
                "proviennent d'une comparaison lexicale et doivent etre "
                "consideres comme indicatifs."
            )
            score = None

        audit.compliance_score = score
        audit.status = AuditStatus.COMPLETED
        audit.completed_at = datetime.now(timezone.utc)
        audit.error_message = warning
        db.flush()

        logger.info(
            "Audit %s : %d exigences, %d hors perimetre par eligibilite, "
            "%d non applicables au total, %d constats, score %s",
            audit.id, len(requirements), len(exemptees), not_applicable,
            len(findings), score,
        )

        return AuditOutcome(
            audit_id=audit.id, status=audit.status, score=score,
            findings=len(findings), evaluated=len(requirements),
            message=warning, degraded=degraded, fallbacks=fallbacks,
            not_applicable=not_applicable,
        )

    except Exception as exc:
        logger.exception("Echec de l'audit %s", audit.id)
        audit.status = AuditStatus.FAILED
        audit.error_message = str(exc)[:2000]
        audit.completed_at = datetime.now(timezone.utc)
        db.flush()
        return AuditOutcome(
            audit_id=audit.id, status=AuditStatus.FAILED, score=None,
            findings=0, evaluated=0, message=str(exc),
        )