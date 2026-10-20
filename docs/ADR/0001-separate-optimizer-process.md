# ADR 0001: Optuna runs in a supervised separate process

Status: accepted (Phase 1)

## Context

PRD v2.1 forbids synchronous Optuna `ask/tell` or statistical work on the
FastAPI event loop. The controller must stay responsive while studies advance,
and controller/Optuna storage must tolerate independent restarts and crashes.

## Decision

`lab_optimizer` is a separate executable process. It owns Optuna
`RDBStorage`, study creation, TPE sampling, trial finalization and health.
The controller communicates only through durable `optimizer_requests` rows and
authenticated internal HTTP endpoints. FastAPI never imports Optuna and never
opens the Optuna database.

## Consequences

- Two processes, two databases, one durable protocol.
- Controller and optimizer can crash/restart independently.
- Controller commit and `study.tell()` are not atomic; recovery must reconcile
  by stable IDs and must never invent a score or duplicate a trial.
- Deployment must supervise both processes (systemd in later phases).
