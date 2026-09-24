"""Harnais de validation du moteur d'audit -- MOTEUR DE PRODUCTION uniquement
(backend/app/services/audit_engine.py), pas le moteur du laboratoire
(evaluation/). Les deux sont mesures separement : les chiffres de
validation/comparaison_retrievers.json portent sur le second, pas sur ce
qui tourne reellement en production. Ce script sert a mesurer le premier.

Confronte les verdicts du moteur a une verite terrain annotee, et mesure la
reproductibilite en repassant plusieurs fois le meme document.

    python -m validation.evaluate
    python -m validation.evaluate --runs 3
    python -m validation.evaluate --only 01 05 --output rapport.json

Sur le corpus de 15 documents (verite terrain posee article par article,
voir corpus/verite_terrain.json) :

    python -m validation.evaluate --corpus corpus \
        --verite corpus/verite_terrain.json --runs 3 --output rapport.json

Necessite GROQ_API_KEY (le harnais refuse de mesurer l'heuristique de repli,
sans interet) -- environ 700 appels au modele pour 3 passages sur 15
documents x ~45 obligations RGPD. NE PAS lancer cette mesure sans avoir
budgete le quota Groq correspondant.

Le harnais appelle le moteur directement, sans passer par l'API : il n'a besoin
ni d'un serveur lance, ni d'un compte utilisateur.

--------------------------------------------------------------------------
Correspondance avec corpus/verite_terrain.json (Tache 7 du plan de
soutenance) -- lu ici avant d'ecrire une ligne de code d'adaptation
--------------------------------------------------------------------------
Le moteur de production evalue 45 obligations RGPD (articles auditables du
referentiel ingere) ; la verite terrain n'annote que les articles
discriminants pour chaque document (`verdicts_attendus`). Seuls ces
articles annotes sont compares -- les autres ne sont ni comptes corrects ni
comptes en erreur, exactement comme pour annotations.json.

Groupes d'articles ("15-22", "44-49") : verite_terrain.json leur assigne un
verdict UNIQUE (ex. "conforme" pour tout le groupe 15-22), alors que le
moteur evalue chaque article du groupe individuellement. Regle de
comparaison, fixee ICI, avant toute mesure, et jamais modifiee apres coup
quels que soient les resultats obtenus :

    - le groupe observe "manquement" si AU MOINS UN article du groupe est
      observe "manquement" (un seul manquement reel suffit a ne pas
      pouvoir qualifier tout le groupe de conforme) ;
    - sinon, le groupe observe "hors_perimetre" si TOUS les articles du
      groupe le sont ;
    - sinon, "conforme".

Voir _verdict_groupe() ci-dessous.

Profil d'organisation (effectif) : `description` dans verite_terrain.json
mentionne parfois un effectif en toutes lettres (ex. "610 salaries"). Un
motif regex simple (_effectif_depuis_description) l'extrait et le pose sur
`headcount` de l'organisation de test, pour que le filtre d'eligibilite
(app/services/eligibilite.py, article 30) dispose de la meme information
qu'un auditeur lisant le document. Choix documente ici : c'est une
extraction heuristique sur un texte redige a la main, pas un champ
structure -- elle peut echouer silencieusement (headcount reste None) sans
que cela invalide la mesure, puisque le filtre repond alors "a verifier"
plutot que d'exempter a tort.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from validation.harnais import CasDeTest, charger_verite_terrain, wilson

VALIDATION_DIR = pathlib.Path(__file__).resolve().parent
CORPUS_DIR = VALIDATION_DIR / "corpus"
ANNOTATIONS = VALIDATION_DIR / "annotations.json"

_EFFECTIF_RE = re.compile(r"(\d[\d\s]{0,6}\d|\d)\s*salari[ée]s?", re.IGNORECASE)


def _effectif_depuis_description(description: str) -> int | None:
    match = _EFFECTIF_RE.search(description)
    if not match:
        return None
    try:
        return int(match.group(1).replace(" ", ""))
    except ValueError:
        return None


def _verdict_groupe(observed: dict[str, str], plage: str) -> str:
    """Agrege le verdict observe sur un groupe d'articles ("15-22", "44-49").

    Regle fixee et documentee dans le docstring du module -- jamais ajustee
    apres avoir vu un resultat de mesure.
    """
    debut, fin = (int(x) for x in plage.split("-"))
    verdicts = [observed.get(str(n), "conforme") for n in range(debut, fin + 1)]
    if any(v == "manquement" for v in verdicts):
        return "manquement"
    if all(v == "hors_perimetre" for v in verdicts):
        return "hors_perimetre"
    return "conforme"


def _adapter_verite_terrain(cas: list[CasDeTest]) -> dict[str, dict[str, Any]]:
    """Traduit le format de corpus/verite_terrain.json (Tache 7) vers le
    format attendu par evaluate() (celui d'annotations.json) : un verdict
    "tolere" n'existe pas dans verite_terrain.json (verite posee sans
    ambiguite assumee), donc jamais produit ici.
    """
    return {
        c.fichier: {
            "profil": c.description,
            "score_attendu": list(c.score_attendu),
            "articles": {
                article: {"verdict": verdict}
                for article, verdict in c.verdicts_attendus.items()
            },
        }
        for c in cas
    }


# --------------------------------------------------------------------------
# Correspondance entre verdict du moteur et verdict annote
# --------------------------------------------------------------------------
def observed_verdict(finding: Any | None, is_out_of_scope: bool) -> str:
    """Traduit le resultat du moteur dans le vocabulaire des annotations.

    Le moteur produit trois etats observables pour une exigence :
    - un constat de gravite critique ou majeure  -> manquement
    - un constat de gravite mineure ou info      -> conforme (axe d'amelioration)
    - un statut non applicable, ou aucun constat -> hors perimetre / conforme

    Un axe d'amelioration est compte comme conforme : l'obligation est traitee,
    la remarque porte sur la formalisation. C'est la lecture d'un auditeur.
    """
    from app.models.enums import FindingStatus, Severity

    if is_out_of_scope:
        return "hors_perimetre"
    if finding is None:
        return "conforme"
    if finding.status is FindingStatus.NOT_APPLICABLE:
        return "hors_perimetre"
    if finding.severity in (Severity.CRITICAL, Severity.MAJOR):
        return "manquement"
    return "conforme"


@dataclass
class ArticleResult:
    article: str
    expected: str
    observed: str
    tolerated: bool

    @property
    def correct(self) -> bool:
        return self.tolerated or self.expected == self.observed


@dataclass
class DocumentRun:
    document: str
    score: float | None
    degraded: bool
    articles: dict[str, str] = field(default_factory=dict)
    # Metriques d'execution (Tache 3 : app/models/audit.py) -- None si le
    # passage a echoue avant meme le calcul (audit introuvable).
    retriever: str | None = None
    llm_model: str | None = None
    llm_calls: int | None = None
    llm_prompt_tokens: int | None = None
    llm_completion_tokens: int | None = None
    duration_seconds: float | None = None


@dataclass
class DocumentReport:
    document: str
    profile: str
    expected_range: tuple[int, int]
    runs: list[DocumentRun] = field(default_factory=list)
    results: list[ArticleResult] = field(default_factory=list)

    @property
    def scores(self) -> list[float]:
        return [r.score for r in self.runs if r.score is not None]

    @property
    def score_in_range(self) -> bool:
        if not self.scores:
            return False
        low, high = self.expected_range
        return low <= statistics.mean(self.scores) <= high

    @property
    def score_gap(self) -> float:
        """Ecart a l'intervalle attendu. Zero si dedans."""
        if not self.scores:
            return 100.0
        mean = statistics.mean(self.scores)
        low, high = self.expected_range
        if mean < low:
            return low - mean
        if mean > high:
            return mean - high
        return 0.0

    @property
    def stability(self) -> float:
        """Proportion d'articles au verdict identique sur tous les passages."""
        if len(self.runs) < 2:
            return 1.0
        articles = self.runs[0].articles.keys()
        if not articles:
            return 1.0
        stable = sum(
            1 for a in articles
            if len({run.articles.get(a) for run in self.runs}) == 1
        )
        return stable / len(articles)


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------
def run_document(
    db, org_id, user_id, path: pathlib.Path, index: int
) -> DocumentRun:
    """Cree un audit, depose le document, lance l'analyse, releve les verdicts."""
    from app.models.audit import Audit, Document, Finding
    from app.models.enums import Framework
    from app.services import audit_engine
    from app.services.documents import save_document

    content = path.read_bytes()
    audit = Audit(
        organization_id=org_id,
        created_by_id=user_id,
        title=f"[validation] {path.stem} #{index}",
        framework=Framework.RGPD,
    )
    db.add(audit)
    db.flush()

    key, digest = save_document(org_id, path.name, content)
    db.add(
        Document(
            audit_id=audit.id,
            organization_id=org_id,
            uploaded_by_id=user_id,
            filename=path.name,
            mime_type="text/plain",
            size_bytes=len(content),
            sha256=digest,
            storage_key=key,
        )
    )
    db.flush()

    outcome = audit_engine.run_audit(db, audit)
    db.flush()

    findings = {
        f.article_ref: f
        for f in db.query(Finding).filter(Finding.audit_id == audit.id).all()
    }

    verdicts: dict[str, str] = {}
    for reference, finding in findings.items():
        number = reference.replace("Article", "").strip()
        verdicts[number] = observed_verdict(finding, is_out_of_scope=False)

    return DocumentRun(
        document=path.name,
        score=outcome.score,
        degraded=outcome.degraded,
        articles=verdicts,
        retriever=audit.retriever,
        llm_model=audit.llm_model,
        llm_calls=audit.llm_calls,
        llm_prompt_tokens=audit.llm_prompt_tokens,
        llm_completion_tokens=audit.llm_completion_tokens,
        duration_seconds=audit.duration_seconds,
    )


def evaluate(
    runs_per_document: int,
    only: list[str] | None,
    corpus_dir: pathlib.Path = CORPUS_DIR,
    verite_path: pathlib.Path | None = None,
) -> list[DocumentReport]:
    from app.db.session import SessionLocal
    from app.models.enums import OrgRole
    from app.models.organization import Membership, Organization
    from app.models.user import User

    if verite_path is not None:
        annotations = _adapter_verite_terrain(charger_verite_terrain(verite_path))
    else:
        annotations = json.loads(ANNOTATIONS.read_text(encoding="utf-8"))

    documents = sorted(p for p in corpus_dir.glob("*.txt"))
    if only:
        documents = [p for p in documents if any(p.name.startswith(k) for k in only)]

    if not documents:
        print("Aucun document du corpus ne correspond.", file=sys.stderr)
        return []

    reports: list[DocumentReport] = []

    with SessionLocal() as db:
        # Organisation technique dediee : les audits de validation ne doivent
        # pas polluer les donnees d'un utilisateur reel.
        suffix = uuid.uuid4().hex[:8]
        user = User(
            email=f"validation-{suffix}@interne.local",
            password_hash="!",
            full_name="Harnais de validation",
            is_active=False,
        )
        org = Organization(name="Validation", slug=f"validation-{suffix}")
        db.add_all([user, org])
        db.flush()
        db.add(Membership(user_id=user.id, organization_id=org.id, role=OrgRole.OWNER))
        db.flush()

        for path in documents:
            spec = annotations.get(path.name)
            if spec is None:
                print(f"  (ignore : {path.name} n'est pas annote)")
                continue

            # Effectif pose sur l'organisation de test quand la description le
            # mentionne (voir _effectif_depuis_description dans le docstring
            # du module) : le filtre d'eligibilite (article 30) doit disposer
            # de la meme information qu'un auditeur lisant le document.
            org.headcount = _effectif_depuis_description(spec.get("profil", ""))
            db.flush()

            low, high = spec["score_attendu"]
            report = DocumentReport(
                document=path.name,
                profile=spec["profil"],
                expected_range=(low, high),
            )

            for index in range(1, runs_per_document + 1):
                print(f"  {path.name} — passage {index}/{runs_per_document}…", flush=True)
                report.runs.append(run_document(db, org.id, user.id, path, index))
                db.commit()

            # Comparaison au premier passage, celui de reference.
            observed = report.runs[0].articles
            for article, expectation in spec["articles"].items():
                expected = expectation["verdict"]
                observed_value = (
                    _verdict_groupe(observed, article)
                    if "-" in article
                    else observed.get(article, "conforme")
                )
                report.results.append(
                    ArticleResult(
                        article=article,
                        expected="conforme" if expected == "tolere" else expected,
                        observed=observed_value,
                        tolerated=expected == "tolere",
                    )
                )

            reports.append(report)

    return reports


# --------------------------------------------------------------------------
# Metriques
# --------------------------------------------------------------------------
def compute_metrics(reports: list[DocumentReport]) -> dict[str, Any]:
    results = [r for report in reports for r in report.results]
    counted = [r for r in results if not r.tolerated]

    # Detection des manquements : la metrique qui compte pour un auditeur.
    tp = sum(1 for r in counted if r.expected == "manquement" and r.observed == "manquement")
    fn = sum(1 for r in counted if r.expected == "manquement" and r.observed != "manquement")
    fp = sum(1 for r in counted if r.expected != "manquement" and r.observed == "manquement")

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    # Exclusions : une exclusion abusive fait disparaitre une obligation reelle.
    scope_expected = [r for r in counted if r.expected == "hors_perimetre"]
    scope_ok = sum(1 for r in scope_expected if r.observed == "hors_perimetre")
    wrongly_excluded = sum(
        1 for r in counted if r.expected == "manquement" and r.observed == "hors_perimetre"
    )

    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in counted:
        confusion[r.expected][r.observed] += 1

    corrects = sum(1 for r in counted if r.correct)
    ic_bas, ic_haut = wilson(corrects, len(counted)) if counted else (0.0, 0.0)

    return {
        "articles_evalues": len(results),
        "articles_comptes": len(counted),
        "articles_tolerés": len(results) - len(counted),
        "exactitude": corrects / len(counted) if counted else 0.0,
        # Intervalle de confiance de Wilson (95 %) sur l'exactitude, fiable
        # sur le petit effectif de ce corpus (validation/harnais.py::wilson).
        "exactitude_ic95": [ic_bas, ic_haut],
        "detection_manquements": {
            "precision": precision,
            "rappel": recall,
            "f1": f1,
            "vrais_positifs": tp,
            "faux_positifs": fp,
            "faux_negatifs": fn,
        },
        "perimetre": {
            "exclusions_attendues": len(scope_expected),
            "exclusions_correctes": scope_ok,
            "taux": scope_ok / len(scope_expected) if scope_expected else 0.0,
            "exclusions_abusives": wrongly_excluded,
        },
        "score": {
            "documents_dans_intervalle": sum(1 for r in reports if r.score_in_range),
            "documents_total": len(reports),
            "ecart_moyen": (
                statistics.mean([r.score_gap for r in reports]) if reports else 0.0
            ),
        },
        "reproductibilite": {
            "stabilite_moyenne": (
                statistics.mean([r.stability for r in reports]) if reports else 1.0
            ),
            "ecart_type_score_max": max(
                (statistics.pstdev(r.scores) if len(r.scores) > 1 else 0.0)
                for r in reports
            ) if reports else 0.0,
        },
        "matrice_confusion": {k: dict(v) for k, v in confusion.items()},
    }


def print_report(reports: list[DocumentReport], metrics: dict[str, Any]) -> None:
    line = "=" * 72
    print(f"\n{line}\nRESULTATS PAR DOCUMENT\n{line}")

    for report in reports:
        mean = statistics.mean(report.scores) if report.scores else None
        low, high = report.expected_range
        verdict = "OK " if report.score_in_range else "ECART"
        shown = f"{mean:.1f}" if mean is not None else "n/d"
        print(f"\n{report.document}  —  {report.profile}")
        print(f"  Score      : {shown} (attendu {low}-{high})  [{verdict}]")
        if len(report.runs) > 1:
            values = ", ".join(f"{s:.1f}" for s in report.scores)
            print(f"  Passages   : {values}")
            print(f"  Stabilite  : {report.stability:.0%} des articles au verdict constant")

        errors = [r for r in report.results if not r.correct]
        counted = [r for r in report.results if not r.tolerated]
        print(f"  Articles   : {len(counted) - len(errors)}/{len(counted)} corrects")
        for r in errors:
            print(f"    Article {r.article:<4} attendu {r.expected:<15} obtenu {r.observed}")

    print(f"\n{line}\nMETRIQUES GLOBALES\n{line}")
    d = metrics["detection_manquements"]
    ic_bas, ic_haut = metrics["exactitude_ic95"]
    print(f"\n  Exactitude globale        : {metrics['exactitude']:.1%} "
          f"sur {metrics['articles_comptes']} articles")
    print(f"    IC 95 % (Wilson)        : [{ic_bas:.1%} — {ic_haut:.1%}]")
    print("\n  Detection des manquements")
    print(f"    Precision               : {d['precision']:.1%}  "
          f"(un manquement annonce est reel)")
    print(f"    Rappel                  : {d['rappel']:.1%}  "
          f"(un manquement reel est detecte)")
    print(f"    F1                      : {d['f1']:.1%}")
    print(f"    Faux positifs           : {d['faux_positifs']}")
    print(f"    Faux negatifs           : {d['faux_negatifs']}")

    p = metrics["perimetre"]
    print("\n  Perimetre")
    print(f"    Exclusions correctes    : {p['exclusions_correctes']}/"
          f"{p['exclusions_attendues']} ({p['taux']:.1%})")
    print(f"    Exclusions abusives     : {p['exclusions_abusives']}  "
          f"(obligation reelle ecartee)")

    s = metrics["score"]
    print("\n  Score de conformite")
    print(f"    Dans l'intervalle       : {s['documents_dans_intervalle']}/"
          f"{s['documents_total']} documents")
    print(f"    Ecart moyen             : {s['ecart_moyen']:.1f} points")

    r = metrics["reproductibilite"]
    print("\n  Reproductibilite")
    print(f"    Verdicts stables        : {r['stabilite_moyenne']:.1%}")
    print(f"    Ecart-type du score max : {r['ecart_type_score_max']:.2f} points")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Validation du moteur d'audit.")
    parser.add_argument("--runs", type=int, default=1,
                        help="passages par document (>= 2 pour mesurer la variance)")
    parser.add_argument("--only", nargs="*", help="prefixes de documents, ex. 01 05")
    parser.add_argument("--output", help="fichier JSON de sortie")
    parser.add_argument("--corpus", type=pathlib.Path, default=CORPUS_DIR,
                        help="dossier de documents .txt (defaut : validation/corpus)")
    parser.add_argument("--verite", type=pathlib.Path, default=None,
                        help="verite terrain au format corpus/verite_terrain.json "
                             "(defaut : validation/annotations.json)")
    parser.add_argument(
        "--sans-modele", action="store_true",
        help="AUTORISE une execution sans GROQ_API_KEY (heuristique de repli "
             "uniquement) -- verification que le script tourne de bout en "
             "bout, PAS une mesure valide : ne jamais citer un resultat "
             "obtenu avec ce drapeau.",
    )
    args = parser.parse_args()

    from app.services import llm

    if not llm.is_available() and not args.sans_modele:
        print("ATTENTION : aucun modele de langage disponible.")
        print("La validation mesurerait l'heuristique de repli, sans interet.")
        print("Renseigner GROQ_API_KEY dans .env avant de relancer, ou passer")
        print("--sans-modele pour une simple verification de bout en bout.\n")
        return 1
    if args.sans_modele:
        print("--sans-modele : execution sans LLM, verification uniquement, "
              "resultats NON valides pour le memoire.\n")

    print(f"Corpus : {args.corpus}")
    print(f"Verite terrain : {args.verite or ANNOTATIONS}")
    print(f"Passages par document : {args.runs}\n")

    reports = evaluate(args.runs, args.only, corpus_dir=args.corpus, verite_path=args.verite)
    if not reports:
        return 1

    metrics = compute_metrics(reports)
    print_report(reports, metrics)

    if args.output:
        payload = {
            "date": datetime.now(timezone.utc).isoformat(),
            "passages_par_document": args.runs,
            "corpus": str(args.corpus),
            "verite_terrain": str(args.verite or ANNOTATIONS),
            "sans_modele": args.sans_modele,
            "metriques": metrics,
            "documents": [
                {
                    "document": r.document,
                    "profil": r.profile,
                    "intervalle_attendu": list(r.expected_range),
                    "scores": r.scores,
                    "stabilite": r.stability,
                    "articles": [
                        {"article": a.article, "attendu": a.expected,
                         "obtenu": a.observed, "tolere": a.tolerated}
                        for a in r.results
                    ],
                    "execution": [
                        {
                            "retriever": run.retriever, "modele": run.llm_model,
                            "appels": run.llm_calls,
                            "jetons_prompt": run.llm_prompt_tokens,
                            "jetons_completion": run.llm_completion_tokens,
                            "duree_s": run.duration_seconds,
                        }
                        for run in r.runs
                    ],
                }
                for r in reports
            ],
        }
        pathlib.Path(args.output).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"Rapport ecrit dans {args.output}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
