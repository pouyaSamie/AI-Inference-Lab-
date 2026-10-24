# ADR 0021: Managed local serving from validated recipes

Date: 2026-10-23. Status: implemented candidate; live acceptance pending.

The operator requested both a built-in chat and a local endpoint using best
recipes. The renderer must remain isolated, workers must remain outbound-only,
and interactive requests must not become optimization evidence.

Use typed RUN_RECIPE, STOP_RECIPE and RECIPE_CHAT durable worker commands.
Authenticated operator requests freeze the original candidate and model identity;
the worker reconstructs its adapter's serving plan and rechecks installed bytes.
A worker owns at most one session and its GPU lease/process journal. Stop targets
a session identity, never an arbitrary PID. Stop during startup cannot release
the GPU before its owned process stops. Heartbeats carry serving health into a
separate WorkerRow field, not into immutable discovery/benchmark evidence.

The chat uses engine token counting and bounded local HTTP requests. The
controller never connects inbound to a worker or engine. Prompts and replies
are retained only in the local command store and are not diagnostic log fields.
No chat result can qualify a recipe. Real/simulated lanes remain separate.

Existing recipes remain immutable, including legacy Strata manifests lacking a
standalone launch profile. Managed Run reconstructs the native profile using the
retained candidate and compares its native profile identity. Metadata export is
labelled accordingly rather than pretending the old Bash recipe is executable.
External service replacement, automatic restart, proxy rebinding, automatic
promotion and systemd deployment are not part of this local serving increment.

An additive controller migration stores current serving health. Older packages
will refuse the newer schema; rollback requires verified stopped-store snapshots
and preserves newer stores separately. The optimizer database remains separate.
