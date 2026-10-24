# ADR 0019 — Explicit desktop engine management

Date: 2026-10-21. Status: accepted for the user-requested desktop increment.

The operator requested latest-build recommendations, online update suggestions
at startup, confirmed installation and old-build removal. This explicitly expands
the earlier offline-only desktop scope. The PRD has not been rewritten; controller
release import, pure adapters and evidence qualification retain their existing
contracts and offline behavior.

Electron main owns a separate fixed-source updater for official llama.cpp and
Strata GitHub releases. Startup metadata checks default on in this requested
workflow and can be disabled through a persisted preference. Checks send no local
paths, model identities, secrets or hardware inventory. Rate-limit/offline failures
do not block the local runtime. No artifact installation occurs at startup.

Recommendations use identifiable build metadata and completeness of supporting
files; they are not benchmark recommendations. Folder names and same-base local
development builds cannot establish an authoritative upstream upgrade direction.
Stable llama.cpp release pointers are checksum verified and resolve the matching
binary release. Strata's native version is distinct from its desktop version.

Installation requires an explicit native confirmation and a selected architecture/
backend asset. Only offered official assets with SHA-256 digests can be downloaded.
The downloader limits bytes/redirect hosts/time; bundled Python extracts bounded
safe tar entries into a new private staging directory. Strata requires matching
verified server/control and interpreter files. No shell/installer script or engine
is executed by the installer. Successful installs are published atomically beside
existing builds. Selection and normal worker capability verification are separate.

An idle runtime is required for engine changes. Services restart to discover a
successfully published installation; failed downloads leave them running. Engine operations are serialized
with configuration changes; renderer mutations are blocked during them. Quit
cancels active downloads/extraction, waits for staging cleanup and stops services.
No installation grants evidence qualification or silently updates old experiments.

Removal uses native confirmation and Trash for inactive isolated build directories.
Selected engines, shared files, model-containing directories and broad source/
runtime roots are protected. This preserves an opportunity to validate a new build
before removing the previous one. No automatic old-build deletion is performed.

The close button always offers Quit, Minimize to tray (taskbar fallback), or Cancel.
Destroyed-window cleanup uses the sender ID captured while the window is alive.
