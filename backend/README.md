# BNI Soignies Hub API

Backend Flask de BNI Soignies Hub.

## Socle V0.1
- PostgreSQL via `DATABASE_URL`
- Membres + périodes d'adhésion
- Mandats
- Rôles + affectations
- Réunions
- API santé : `/health`
- API : `/api`
- Membres : `/api/members`
- Réunions : `/api/meetings`

Les tables sont créées au démarrage pour cette première phase. Les migrations Alembic seront ajoutées avant les évolutions de schéma en production.
