"""Masque le referentiel CSRD dans l'interface (is_active = false).

Decision produit : le CSRD reste ingere et pleinement fonctionnel cote
backend (connecteur, scoping, exigences en base), mais n'est plus propose
dans l'application -- ni dans les selecteurs de campagne/correspondances/
referentiels, ni dans le contenu marketing de l'accueil et de la page A
propos (voir le commit frontend correspondant). Reversible : il suffit de
repasser cette ligne a `true` (ou de retirer "csrd" de
app.ingestion.runner.FRAMEWORKS_MASQUES avant une reingestion) pour le
reactiver, sans aucune perte de donnees.

Un UPDATE cible plutot qu'une suppression : les audits deja lances sur ce
referentiel (s'il y en a) doivent continuer a s'afficher normalement.

Revision ID: 0010_masque_csrd
Revises: 0009_csrd_framework_enum
"""

from alembic import op

revision = "0010_masque_csrd"
down_revision = "0009_csrd_framework_enum"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE frameworks SET is_active = false WHERE code = 'csrd'")


def downgrade() -> None:
    op.execute("UPDATE frameworks SET is_active = true WHERE code = 'csrd'")
