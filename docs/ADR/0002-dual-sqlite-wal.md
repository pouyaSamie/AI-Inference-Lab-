# ADR 0002: Separate SQLite WAL stores for controller and optimizer

Status: accepted (Phase 1, standalone mode)

## Context

SQLite permits concurrent readers but only one writer per database file.
Putting controller job writes and Optuna study writes in one file creates
cross-component lock contention and couples failure domains. PostgreSQL is the
future central option, but the local-first mode must work without a server.

## Decision

Standalone deployments use two independent SQLite files:

- `var/controller.sqlite3` for the controller;
- `var/optuna.sqlite3` for Optuna RDBStorage.

Both use WAL, a configured busy timeout and `synchronous=FULL` by default.
`Settings` rejects equal URLs or equal resolved SQLite paths. Controller schema
is Alembic-managed; Optuna owns its own storage schema.

## Consequences

- Better read/write concurrency and independent recovery.
- Cross-store operations are not transactional and require durable reconciliation.
- Operators must back up both stores and their WAL/SHM files consistently.
