"""Generation des rapports d'audit, versionnes et horodates."""

from __future__ import annotations

import hashlib
import html
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.audit import Audit, Finding, Report
from app.models.enums import FindingStatus, Severity
from app.services.audit_engine import NON_CONFORMITY_SEVERITIES
from app.services.documents import storage_root

SEVERITY_LABEL = {
    Severity.CRITICAL: ("Critique", "#C0342A", "#FDECEA"),
    Severity.MAJOR: ("Majeure", "#B4720C", "#FDF2DD"),
    Severity.MINOR: ("Mineure", "#3457D5", "#EAEEFD"),
    Severity.INFO: ("Information", "#565A73", "#EFF1F7"),
}


def _render_html(audit: Audit, findings: list[Finding], version: int) -> str:
    # Trois categories : ce qui manque, ce qui peut etre ameliore, et ce qui
    # ne concerne pas l'organisation. Seules les deux premieres comptent dans
    # le score et dans les compteurs de gravite.
    out_of_scope = [f for f in findings if f.status is FindingStatus.NOT_APPLICABLE]
    in_scope = [f for f in findings if f.status is not FindingStatus.NOT_APPLICABLE]
    non_conformities = [f for f in in_scope if f.severity in NON_CONFORMITY_SEVERITIES]
    improvements = [f for f in in_scope if f.severity not in NON_CONFORMITY_SEVERITIES]

    counts = {s: sum(1 for f in in_scope if f.severity == s) for s in Severity}
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y à %H:%M UTC")
    publie = audit.compliance_score is not None
    score = f"{audit.compliance_score:.1f}" if publie else "—"

    def finding_card(f: Finding) -> str:
        label, color, bg = SEVERITY_LABEL[f.severity]
        title = (f.title or "").strip()
        return f"""<article class="carte-constat">
  <div class="dos">
    <span class="ref">{html.escape(f.article_ref)}</span>
    <span class="badge" style="color:{color};background:{bg}">{label}</span>
  </div>
  <div class="corps">
    <h3>{html.escape(title)}</h3>
    <p>{html.escape(f.description)}</p>
    {f'<blockquote>{html.escape(f.evidence[:400])}</blockquote>' if f.evidence else ''}
    {f'<div class="reco"><strong>Action corrective</strong>{html.escape(f.recommendation)}</div>' if f.recommendation else ''}
  </div>
</article>"""

    def render_cards(items: list[Finding]) -> str:
        return "\n".join(finding_card(f) for f in items) or '<p class="vide">Rien à signaler.</p>'

    def render_scope_rows(items: list[Finding]) -> str:
        return "\n".join(
            f'<tr><td class="ref-cell">{html.escape(f.article_ref)}</td>'
            f"<td>{html.escape(f.description)}</td></tr>"
            for f in items
        ) or '<tr><td colspan="2">Toutes les exigences du référentiel s\'appliquent.</td></tr>'

    summary = " ".join(
        f'<span class="pill" style="color:{SEVERITY_LABEL[s][1]};background:{SEVERITY_LABEL[s][2]}">'
        f"{SEVERITY_LABEL[s][0]} · {counts[s]}</span>"
        for s in Severity if counts[s]
    ) or '<span class="pill" style="color:#178A4C;background:#E7F8EE">Aucune non-conformité</span>'

    warning_banner = (
        f'<div class="alerte"><strong>Analyse dégradée.</strong> '
        f'{html.escape(audit.error_message)}</div>'
        if audit.error_message else ""
    )

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Rapport d'audit — {html.escape(audit.title)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 20mm 16mm 22mm; }}
  * {{ box-sizing: border-box }}
  body {{ font-family: 'Inter', system-ui, sans-serif; max-width: 880px; margin: 0 auto;
         color: #12142B; line-height: 1.55; padding: 36px 28px 60px; font-size: 13.5px; }}
  h1, h2, h3 {{ font-family: 'Sora', 'Inter', sans-serif; letter-spacing: -.01em }}
  header.tete {{ display: flex; justify-content: space-between; align-items: flex-start;
         border-bottom: 2px solid #12142B; padding-bottom: 18px; margin-bottom: 24px; gap: 20px; }}
  .marque {{ font-family: 'Sora', sans-serif; font-weight: 700; font-size: 15px; color: #4338CA }}
  h1 {{ font-size: 22px; font-weight: 800; margin: 4px 0 6px; }}
  .subtitle {{ color: #565A73; font-size: 12.5px; }}
  .meta-droite {{ text-align: right; font-family: 'IBM Plex Mono', monospace; font-size: 10.5px;
                  color: #8A8EA6; white-space: nowrap; }}

  .verdict {{ display: flex; align-items: center; gap: 28px; background: linear-gradient(160deg,#fff 55%,#EEF0FE 130%);
              border: 1px solid #E7E9F2; border-radius: 14px; padding: 22px 26px; margin-bottom: 22px; }}
  .score {{ font-family: 'Sora', sans-serif; font-size: 44px; font-weight: 800; line-height: 1;
            background: linear-gradient(135deg,#6D6BF5,#4C3FE0); -webkit-background-clip: text;
            background-clip: text; color: transparent; white-space: nowrap; }}
  .score .unite {{ font-size: 16px; color: #8A8EA6; -webkit-text-fill-color: #8A8EA6; font-family: 'Inter', sans-serif }}
  .verdict-corps {{ flex: 1 }}
  .pill {{ padding: 3px 10px; border-radius: 999px; font-size: 10.5px; font-weight: 600;
           font-family: 'IBM Plex Mono', monospace; letter-spacing: .02em; display: inline-block;
           margin: 2px 4px 2px 0; }}

  h2 {{ font-size: 15px; font-weight: 700; margin: 30px 0 3px; break-after: avoid; }}
  .lead {{ color: #565A73; font-size: 12px; margin: 0 0 14px; }}

  .carte-constat {{ display: grid; grid-template-columns: 96px 1fr; gap: 16px; padding: 14px 0;
                     border-bottom: 1px solid #EFF1F7; break-inside: avoid; page-break-inside: avoid; }}
  .carte-constat .dos {{ padding-top: 2px }}
  .ref {{ font-family: 'IBM Plex Mono', monospace; font-size: 11px; font-weight: 600; display: block; margin-bottom: 6px; }}
  .badge {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; font-weight: 600; letter-spacing: .03em;
            text-transform: uppercase; padding: 2px 7px; border-radius: 999px; display: inline-block; white-space: nowrap; }}
  .corps h3 {{ font-size: 13.5px; font-weight: 700; margin: 0 0 5px; }}
  .corps p {{ margin: 0 0 7px; color: #333648; }}
  blockquote {{ border-left: 2px solid #E7E9F2; margin: 6px 0; padding: 2px 12px; color: #565A73;
                font-size: 12px; font-style: italic; }}
  .reco {{ background: #E7F8EE; border-left: 2px solid #178A4C; border-radius: 0 6px 6px 0;
           padding: 8px 12px; font-size: 12px; margin-top: 6px; }}
  .reco strong {{ font-family: 'IBM Plex Mono', monospace; font-size: 9px; letter-spacing: .04em;
                  text-transform: uppercase; color: #178A4C; display: block; margin-bottom: 2px; }}
  .provenance {{ font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: #8A8EA6; margin-top: 6px; }}
  .vide {{ color: #8A8EA6; font-size: 12.5px; font-style: italic; }}

  table {{ width: 100%; border-collapse: collapse; margin-top: 6px; font-size: 12px; }}
  th {{ text-align: left; background: #F5F6FB; padding: 8px 10px; font-family: 'IBM Plex Mono', monospace;
        font-size: 9.5px; letter-spacing: .03em; text-transform: uppercase; color: #8A8EA6; }}
  td {{ border-bottom: 1px solid #EFF1F7; padding: 8px 10px; vertical-align: top; color: #333648; }}
  td.ref-cell {{ white-space: nowrap; font-family: 'IBM Plex Mono', monospace; font-weight: 600; width: 100px; }}

  .alerte {{ border-left: 3px solid #C0342A; background: #FDECEA; border-radius: 0 8px 8px 0;
             padding: 10px 14px; margin: 0 0 18px; font-size: 12.5px; color: #7A241D; }}
  footer {{ margin-top: 36px; padding-top: 14px; border-top: 1px solid #E7E9F2;
            font-size: 10.5px; color: #8A8EA6; }}
</style></head><body>
<header class="tete">
  <div>
    <div class="marque">ComplianceAI Studio</div>
    <h1>{html.escape(audit.title)}</h1>
    <div class="subtitle">Rapport d'audit de conformité · Référentiel {html.escape(audit.framework.value.upper())}</div>
  </div>
  <div class="meta-droite">Version {version}<br>{generated}</div>
</header>

{warning_banner}

<div class="verdict">
  <div class="score">{score}<span class="unite">/100</span></div>
  <div class="verdict-corps">{summary}</div>
</div>

<h2>Non-conformités ({len(non_conformities)})</h2>
<p class="lead">Manquements à une obligation substantielle. À traiter en priorité.</p>
{render_cards(non_conformities)}

<h2>Axes d'amélioration ({len(improvements)})</h2>
<p class="lead">Obligations traitées, mais dont la formalisation peut être complétée.</p>
{render_cards(improvements)}

<h2>Exigences hors périmètre ({len(out_of_scope)})</h2>
<p class="lead">
  Articles écartés du calcul du score : ils portent sur des situations absentes
  de l'activité auditée. Cette liste est fournie pour que l'exclusion puisse
  être vérifiée et contestée.
</p>
<table>
  <thead><tr><th>Référence</th><th>Motif de l'exclusion</th></tr></thead>
  <tbody>{render_scope_rows(out_of_scope)}</tbody>
</table>

<footer>
  Rapport généré automatiquement par ComplianceAI Studio. Les constats sont
  produits par analyse assistée des documents fournis et citent l'article dont
  ils découlent. Ils ne constituent pas un avis juridique et doivent être
  validés par un professionnel avant toute décision engageante.
</footer>
</body></html>"""


def generate_report(db: Session, audit: Audit, user_id=None) -> Report:
    # Verrou consultatif transactionnel, scope a cet audit : sans lui, deux
    # requetes "produire un rapport" simultanees lisent le meme dernier
    # numero de version, ecrivent sur le meme fichier (la derniere ecriture
    # l'emporte silencieusement) puis se disputent la contrainte d'unicite en
    # base -- la perdante remonte une IntegrityError brute, et le fichier
    # laisse sur disque peut ne plus correspondre au sha256 finalement
    # enregistre. Bloquant (pas *_try_*) : la seconde requete attend
    # simplement son tour au lieu d'echouer, un rapport se generant en
    # quelques dizaines de millisecondes. Meme mecanisme que le planificateur
    # (pg_..._xact_lock) : liberation automatique au commit/rollback de la
    # requete, jamais de fuite possible en cas d'exception.
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": f"report:{audit.id}"})

    findings = list(
        db.scalars(
            select(Finding)
            .where(Finding.audit_id == audit.id)
            .order_by(Finding.severity, Finding.article_ref)
        )
    )

    last = db.scalar(
        select(Report).where(Report.audit_id == audit.id).order_by(Report.version.desc())
    )
    version = (last.version + 1) if last else 1

    # Le resume ne compte que les exigences applicables : les exclusions sont
    # listees a part et ne doivent pas apparaitre dans les statistiques.
    scoped = [f for f in findings if f.status is not FindingStatus.NOT_APPLICABLE]

    content = _render_html(audit, findings, version)
    payload = content.encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()

    key = f"{audit.organization_id}/reports/{audit.id}-v{version}.html"
    target = storage_root() / key
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)

    report = Report(
        audit_id=audit.id,
        version=version,
        storage_key=key,
        sha256=digest,
        summary={
            "score": audit.compliance_score,
            "findings": len(findings),
            "non_conformites": sum(
                1 for f in scoped if f.severity in NON_CONFORMITY_SEVERITIES
            ),
            "ameliorations": sum(
                1 for f in scoped if f.severity not in NON_CONFORMITY_SEVERITIES
            ),
            "hors_perimetre": len(findings) - len(scoped),
            "par_severite": {
                s.value: sum(1 for f in scoped if f.severity == s) for s in Severity
            },
        },
        generated_by_id=user_id,
    )
    db.add(report)
    db.flush()
    return report
