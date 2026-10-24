# ADR 0020: Import verification and hardware-based build recommendations

Status: implemented in desktop 0.5.0, 2026-10-22.

Users should not need to interpret archive backend names or repeatedly request a
plan while model hashing is pending. Electron main detects a read-only hardware
profile once per startup using the bundled interpreter. Release metadata checks
reuse it; a pure selector ranks only matching published assets. Unknown support
requires review. Worker execution checks remain authoritative for actual execution.

NVIDIA recommendations use observed compute capability and conservative driver
requirements rather than assuming PTX/minor compatibility. AMD native targets use
observed gfx identifiers; Vulkan uses physical device support. CPU fallback is
explicit and does not imply support in the current GPU optimization lane.
Relevant upstream references are [NVIDIA toolkit release notes](https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html),
[Strata older GPU support](https://github.com/Niko1221/Strata/blob/main/docs/OLDER_GPUS.md)
and [Strata component metadata](https://github.com/Niko1221/Strata/blob/main/strata_control/components.py).

Import first publishes metadata, then queues durable verification. The worker
hashes files with private progress and a stat-validated hash cache. Each completed
file is persisted; cancellation never saves a partial digest. The renderer reads
progress through validated IPC and waits on durable command status before retrying
snapshot-only planning. It never receives credentials, hashes files itself or
starts execution. Failed verification stops automatic retry and exposes recovery.

Targeted verification is a capability of enrolled upgraded workers. Legacy workers
receive the existing full scan protocol. Generated optional payload fields retain
old default serialization. Full identities, paired evidence and recipe gates remain
unchanged. None of this supplies real engine qualification or broad hardware proof.
