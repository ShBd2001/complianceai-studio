"""Generation des rapports d'audit, versionnes et horodates."""

from __future__ import annotations

import hashlib
import html
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.audit import Audit, Finding, Report
from app.models.enums import FindingStatus, Severity
from app.services.audit_engine import NON_CONFORMITY_SEVERITIES
from app.services.documents import storage_root

SEVERITY_LABEL = {
    Severity.CRITICAL: ("Critique", "#b3261e"),
    Severity.MAJOR: ("Majeure", "#e8710a"),
    Severity.MINOR: ("Mineure", "#f2b705"),
    Severity.INFO: ("Information", "#5b7fa6"),
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
    generated = datetime.now(timezone.utc).strftime("%d/%m/%Y a %H:%M UTC")
    score = f"{audit.compliance_score:.1f}" if audit.compliance_score is not None else "n/d"

    def render_rows(items: list[Finding]) -> str:
        return "\n".join(
            f"""<tr>
  <td class="ref">{html.escape(f.article_ref)}</td>
  <td><span class="sev" style="background:{SEVERITY_LABEL[f.severity][1]}">
      {SEVERITY_LABEL[f.severity][0]}</span></td>
  <td>
    <strong>{html.escape(f.title)}</strong>
    <p>{html.escape(f.description)}</p>
    {f'<p class="reco"><em>Recommandation :</em> {html.escape(f.recommendation)}</p>' if f.recommendation else ''}
    {f'<blockquote>{html.escape(f.evidence[:400])}</blockquote>' if f.evidence else ''}
  </td>
  <td class="meta">{f.model_used or ''}<br>{(f.confidence or 0):.0%}</td>
</tr>"""
            for f in items
        ) or '<tr><td colspan="4">Rien a signaler.</td></tr>'

    def render_scope_rows(items: list[Finding]) -> str:
        return "\n".join(
            f'<tr><td class="ref">{html.escape(f.article_ref)}</td>'
            f"<td>{html.escape(f.description)}</td></tr>"
            for f in items
        ) or '<tr><td colspan="2">Toutes les exigences du referentiel s\'appliquent.</td></tr>'

    summary = " ".join(
        f'<span class="pill" style="background:{SEVERITY_LABEL[s][1]}">'
        f"{SEVERITY_LABEL[s][0]} : {counts[s]}</span>"
        for s in Severity if counts[s]
    ) or '<span class="pill" style="background:#2e7d32">Aucune non-conformite</span>'

    warning_banner = (
        f'<div class="warn"><strong>Analyse degradee.</strong> '
        f'{html.escape(audit.error_message)}</div>'
        if audit.error_message else ""
    )

    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Rapport d'audit — {html.escape(audit.title)}</title>
<style>
  body {{ font-family: Georgia, serif; max-width: 900px; margin: 40px auto;
         color: #1a1a1a; line-height: 1.55; padding: 0 24px; }}
  header {{ border-bottom: 3px solid #1a1a1a; padding-bottom: 16px; margin-bottom: 28px; }}
  h1 {{ font-size: 26px; margin: 0 0 6px; }}
  .subtitle {{ color: #555; font-size: 14px; }}
  .score {{ font-size: 46px; font-weight: bold; margin: 20px 0 6px; }}
  .pill, .sev {{ color: #fff; padding: 3px 10px; border-radius: 12px;
                 font-size: 12px; font-family: system-ui, sans-serif;
                 display: inline-block; white-space: nowrap; }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 24px; font-size: 14px; }}
  th {{ text-align: left; background: #f2f2f2; padding: 10px; font-family: system-ui, sans-serif; }}
  td {{ border-bottom: 1px solid #e0e0e0; padding: 12px 10px; vertical-align: top; }}
  td.ref {{ white-space: nowrap; font-weight: bold; width: 110px; }}
  td.meta {{ font-size: 11px; color: #777; width: 90px; font-family: system-ui, sans-serif; }}
  blockquote {{ border-left: 3px solid #ccc; margin: 8px 0 0; padding: 4px 12px;
                color: #555; font-size: 13px; font-style: italic; }}
  .reco {{ color: #1b5e20; margin: 8px 0 0; }}
  table.compact td {{ font-size: 13px; color: #555; padding: 8px 10px; }}
  .lead {{ color: #555; font-size: 14px; margin: 4px 0 0;
           font-family: system-ui, sans-serif; }}
  .warn {{ border-left: 4px solid #c8651b; background: #fdf6ee; padding: 12px 16px;
           margin: 18px 0; font-size: 14px; font-family: system-ui, sans-serif;
           color: #7a3d0c; }}
  footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #ccc;
            font-size: 12px; color: #666; font-family: system-ui, sans-serif; }}
</style></head><body>
<header>
  <h1>Rapport d'audit de conformite</h1>
  <div class="subtitle">
    {html.escape(audit.title)} · Referentiel {audit.framework.value.upper()} ·
    Version {version} du rapport · Genere le {generated}
  </div>
</header>

{warning_banner}

<div class="score">{score} / 100</div>
<div>{summary}</div>

<h2>Non-conformites ({len(non_conformities)})</h2>
<p class="lead">Manquements a une obligation substantielle. A traiter en priorite.</p>
<table>
  <thead><tr><th>Reference</th><th>Gravite</th><th>Constat et recommandation</th><th>Origine</th></tr></thead>
  <tbody>{render_rows(non_conformities)}</tbody>
</table>

<h2>Axes d'amelioration ({len(improvements)})</h2>
<p class="lead">Obligations traitees, mais dont la formalisation peut etre completee.</p>
<table>
  <thead><tr><th>Reference</th><th>Gravite</th><th>Constat et recommandation</th><th>Origine</th></tr></thead>
  <tbody>{render_rows(improvements)}</tbody>
</table>

<h2>Exigences hors perimetre ({len(out_of_scope)})</h2>
<p class="lead">
  Articles ecartes du calcul du score : ils portent sur des situations absentes
  de l'activite auditee. Cette liste est fournie pour que l'exclusion puisse
  etre verifiee et contestee.
</p>
<table class="compact">
  <thead><tr><th>Reference</th><th>Motif de l'exclusion</th></tr></thead>
  <tbody>{render_scope_rows(out_of_scope)}</tbody>
</table>

<footer>
  Rapport genere automatiquement par ComplianceAI Studio. Les constats sont
  produits par analyse assistee des documents fournis et citent l'article dont
  ils decoulent. Ils ne constituent pas un avis juridique et doivent etre
  valides par un professionnel avant toute decision engageante.
</footer>
</body></html>"""


def generate_report(db: Session, audit: Audit, user_id=None) -> Report:
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
