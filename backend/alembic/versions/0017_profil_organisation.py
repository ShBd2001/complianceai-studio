"""Profil de l'organisation pour le filtre d'eligibilite.

app/services/eligibilite.py::depuis_organisation ne peut aujourd'hui
s'appuyer que sur `headcount` (seul champ existant en base) : le filtre
repond donc presque toujours A_VERIFIER, meme quand l'information est en
realite connue de l'organisation. Les 11 champs ci-dessous sont ceux lus
par cet adaptateur (verifie dans le fichier, pas seulement suppose).

Tous nullable : NULL signifie "non renseigne" et ne doit JAMAIS etre
converti en False par le code applicatif (voir depuis_organisation, qui
respecte deja cette regle).

Revision ID: 0017_profil_organisation
Revises: 0016_audit_run_metrics
"""

import sqlalchemy as sa

from alembic import op

revision = "0017_profil_organisation"
down_revision = "0016_audit_run_metrics"
branch_labels = None
depends_on = None

COLONNES = [
    "organisme_public",
    "donnees_sensibles",
    "donnees_penales",
    "activite_de_base_traitement",
    "suivi_regulier_systematique",
    "grande_echelle",
    "professionnel_liberal_isole",
    "traitement_occasionnel",
    "risque_droits_libertes",
    "collecte_directe",
    "collecte_indirecte",
]


def upgrade() -> None:
    for nom in COLONNES:
        op.add_column("organizations", sa.Column(nom, sa.Boolean(), nullable=True))


def downgrade() -> None:
    for nom in reversed(COLONNES):
        op.drop_column("organizations", nom)
