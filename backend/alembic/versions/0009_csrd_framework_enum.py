"""Ajoute csrd/nist_csf/anssi au type ENUM PostgreSQL `framework`.

Le referentiel CSRD est ingere depuis la mise en place du scoping dedie
(app/ingestion/scoping.py::classify) : 13 exigences dont 5 auditables sont
deja en base. Mais le type ENUM PostgreSQL `framework` sur la colonne
`audits.framework` n'avait jamais ete etendu au-dela de rgpd/nis2/iso27001/
dora/ai_act — toute tentative de creer un audit CSRD echouait donc avec
`InvalidTextRepresentation`, invisible tant qu'aucun audit CSRD n'avait ete
tente. nist_csf et anssi sont ajoutes en meme temps par coherence avec
l'enum Python (app/models/enums.py::Framework), meme si ces deux referentiels
ne sont pas encore ingeres.

Meme contrainte que les revisions precedentes : `ALTER TYPE ... ADD VALUE`
n'est pas reversible, la fonction `downgrade` est donc inerte.

Revision ID: 0009_csrd_framework_enum
Revises: 0008_scheduling
"""

from alembic import op

revision = "0009_csrd_framework_enum"
down_revision = "0008_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE framework ADD VALUE IF NOT EXISTS 'csrd'")
    op.execute("ALTER TYPE framework ADD VALUE IF NOT EXISTS 'nist_csf'")
    op.execute("ALTER TYPE framework ADD VALUE IF NOT EXISTS 'anssi'")


def downgrade() -> None:
    # Le retrait exigerait de recreer le type et de reecrire toutes les colonnes
    # qui l'utilisent, operation disproportionnee au regard du gain.
    pass
