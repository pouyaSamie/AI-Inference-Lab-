# ADR 0010: Alembic owns controller schema; Optuna owns its own schema

Status: accepted (Phase 1)

## Context

Controller and optimizer stores evolve independently. Applying the controller
Alembic tree to the Optuna database would couple versions and risk corrupting
study data.

## Decision

`python/lab_api/migrations` is the only Alembic tree and targets the controller
database (20 tables in the initial revision). The optimizer creates/validates its
Optuna RDBStorage schema independently. Startup does not auto-migrate; operators
run `alembic upgrade head` explicitly.

## Consequences

- Clear ownership and safer upgrades.
- Deployment/runbook must run migrations before serving the new controller.
- Optuna storage compatibility must be tested separately on upgrades.
