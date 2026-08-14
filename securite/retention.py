"""
Rétention et purge des documents audités.

Un outil qui vend de la conformité ne peut pas être en défaut lui-même. Les
documents ingérés (politiques internes, registres, descriptions d'architecture
de sécurité) sont des données sensibles au sens commercial, et contiennent
souvent des données personnelles — un registre nomme le DPO, une politique RH
décrit des traitements de salariés.

Trois obligations dont ComplianceAI Studio est lui-même redevable :
  - durée de conservation limitée et annoncée (art. 5(1)(e)) ;
  - suppression effective sur demande (art. 17) ;
  - chiffrement au repos et minimisation (art. 32 et 5(1)(c)).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum


class Categorie(str, Enum):
    DOCUMENT_SOURCE = "document_source"
    PASSAGES_EMBEDDINGS = "passages_embeddings"
    RAPPORT_AUDIT = "rapport_audit"
    JOURNAL_TECHNIQUE = "journal_technique"


@dataclass(frozen=True)
class ReglRetention:
    categorie: Categorie
    duree: timedelta
    justification: str
    purge_automatique: bool = True


POLITIQUE: dict[Categorie, ReglRetention] = {
    Categorie.DOCUMENT_SOURCE: ReglRetention(
        Categorie.DOCUMENT_SOURCE,
        timedelta(days=90),
        "Le document source n'est nécessaire que le temps de produire et de "
        "contester le rapport. Au-delà, seules les citations retenues sont "
        "conservées, dans le rapport lui-même.",
    ),
    Categorie.PASSAGES_EMBEDDINGS: ReglRetention(
        Categorie.PASSAGES_EMBEDDINGS,
        timedelta(days=90),
        "Les embeddings permettent de reconstituer partiellement le texte "
        "source : ils suivent la même durée que le document.",
    ),
    Categorie.RAPPORT_AUDIT: ReglRetention(
        Categorie.RAPPORT_AUDIT,
        timedelta(days=1095),
        "Trois ans : le client doit pouvoir démontrer sa démarche de mise en "
        "conformité dans la durée et comparer ses audits successifs.",
    ),
    Categorie.JOURNAL_TECHNIQUE: ReglRetention(
        Categorie.JOURNAL_TECHNIQUE,
        timedelta(days=180),
        "Six mois, durée recommandée par la CNIL pour les journaux techniques.",
    ),
}


REQUETES_PURGE: dict[Categorie, str] = {
    Categorie.DOCUMENT_SOURCE: """
        UPDATE documents
        SET contenu = NULL, purge_le = now(), statut = 'purge'
        WHERE cree_le < now() - INTERVAL '90 days'
          AND contenu IS NOT NULL;
    """,
    Categorie.PASSAGES_EMBEDDINGS: """
        DELETE FROM passages
        WHERE document_id IN (
            SELECT id FROM documents WHERE cree_le < now() - INTERVAL '90 days'
        );
    """,
    Categorie.RAPPORT_AUDIT: """
        DELETE FROM rapports_audit
        WHERE cree_le < now() - INTERVAL '1095 days';
    """,
    Categorie.JOURNAL_TECHNIQUE: """
        DELETE FROM journaux
        WHERE horodatage < now() - INTERVAL '180 days';
    """,
}


SUPPRESSION_IMMEDIATE = """
-- Exercice du droit à l'effacement (art. 17) ou résiliation d'un compte.
-- À exécuter dans une transaction unique, dans cet ordre.
BEGIN;
  SELECT set_config('app.tenant_id', %(tenant_id)s, true);
  DELETE FROM verdicts       WHERE tenant_id = %(tenant_id)s;
  DELETE FROM rapports_audit WHERE tenant_id = %(tenant_id)s;
  DELETE FROM passages       WHERE tenant_id = %(tenant_id)s;
  DELETE FROM documents      WHERE tenant_id = %(tenant_id)s;
  INSERT INTO journal_suppressions (tenant_id, demande_le, execute_le, motif)
  VALUES (%(tenant_id)s, %(demande_le)s, now(), %(motif)s);
COMMIT;
"""


def date_purge(cree_le: datetime, categorie: Categorie) -> datetime:
    return cree_le + POLITIQUE[categorie].duree


def a_purger(cree_le: datetime, categorie: Categorie) -> bool:
    return datetime.now(timezone.utc) >= date_purge(cree_le, categorie)


def mention_utilisateur() -> str:
    """Texte à afficher lors du dépôt d'un document. À ne pas enterrer dans les CGU."""
    return (
        "Le document que vous déposez est conservé 90 jours, le temps de produire "
        "et de vous permettre de contester le rapport, puis supprimé automatiquement. "
        "Le rapport d'audit est conservé 3 ans pour vous permettre de suivre votre "
        "démarche de conformité. Vous pouvez demander la suppression immédiate de "
        "l'ensemble de vos données à tout moment depuis les paramètres de votre "
        "compte. Les documents sont chiffrés au repos et ne sont accessibles à "
        "aucun autre client de la plateforme."
    )


def tableau_politique() -> str:
    lignes = [
        f"{'Catégorie':<24} {'Durée':<12} Justification",
        "-" * 100,
    ]
    for regle in POLITIQUE.values():
        jours = f"{regle.duree.days} jours"
        lignes.append(f"{regle.categorie.value:<24} {jours:<12} {regle.justification[:60]}…")
    return "\n".join(lignes)


if __name__ == "__main__":
    print(tableau_politique())
