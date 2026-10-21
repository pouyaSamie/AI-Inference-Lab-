# ADR 0018 — Offline SQLite backup and restore

Status: accepted for Phase 8 offline hardening.

## Context

The controller and optimizer use separate SQLite databases in WAL mode. A
release upgrade or failure recovery may need a consistent copy of both stores
without stopping the controller for a long backup. Restoring a database in place
is also destructive if the target is live or if the only copy is replaced
without evidence.

A backup is useful only if its integrity can be checked later. Copying a live
SQLite file with the filesystem can miss WAL frames; copying only one store can
leave controller and Optuna state inconsistent.

## Decision

1. Use SQLite's online backup API for both backup and restore. The source is
   opened read-only for backup; the destination is built in a temporary file and
   atomically renamed.
2. Require a caller-provided label for each store. Labels are restricted to
   `[a-z0-9][a-z0-9_-]{0,63}` and manifest filenames must be basenames, so a
   manifest cannot escape the backup directory.
3. Write a versioned `manifest.json` containing only labels, basenames, byte
   sizes, SHA-256 digests and `PRAGMA user_version`. Never record absolute source
   paths, tokens or environment values.
4. Verify the manifest, file sizes, digests and `PRAGMA integrity_check` before
   declaring a backup successful and before restoring.
5. Refuse an existing backup directory. This prevents silently mixing two
   generations of evidence.
6. Restoring to an existing target requires an explicit replace decision. The
   existing target is first copied to a verified
   `*.pre-restore-<timestamp>.sqlite3` snapshot. A failed restore must leave that
   snapshot available.
7. Refuse a target with `-wal`/`-shm` sidecars. Restoration is an offline
   operation after all services are stopped; active sidecars indicate an unsafe
   live target.
8. Do not add a controller API or automatic backup daemon. The CLI and runbook
   are operator-controlled. The API never opens, deletes or restores a database
   outside its configured store.

## Consequences

- Backups are transactionally consistent and independently verifiable.
- A restore never silently deletes the previous target, but the operator must
  manage retention and off-host copies.
- A live service must be stopped before restore; there is no online restore.
- A stale empty WAL sidecar can block restore until the operator checkpoints or
  removes it after stopping services. This is deliberately conservative.
- Manifest integrity detects accidental corruption/tampering, not malicious
  replacement of both the manifest and files. Off-host retention and access
  control remain required.
- The runbook, not the code, records the privileged installation and approval
  steps.

## Evidence

`tests/test_backup.py` covers two-store backup/verify/restore, tamper detection,
pre-restore preservation, unsafe labels and sidecar refusal. The CLI was also
exercised on temporary SQLite files. No production database was touched.
