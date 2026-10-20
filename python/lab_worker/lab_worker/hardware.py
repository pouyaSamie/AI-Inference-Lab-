"""Read-only hardware discovery and GPU telemetry for the Linux worker.

No module here installs drivers, changes clocks, terminates processes or writes
to engine/model trees. ``nvidia-smi`` is used because it can be pinned to a GPU
UUID and does not require a Python CUDA dependency.
"""

from __future__ import annotations

import platform
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psutil

from lab_core import GPUDevice, HardwareSnapshot, utcnow

from .config import WorkerSettings


class HardwareDiscoveryError(RuntimeError):
    pass


def _run(argv: tuple[str, ...], *, timeout: float = 10.0) -> str:
    executable = shutil.which(argv[0]) if not argv[0].startswith("/") else argv[0]
    if executable is None:
        raise HardwareDiscoveryError(f"executable not found: {argv[0]}")
    completed = subprocess.run(
        (executable, *argv[1:]),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"},
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout).strip()[:500]
        raise HardwareDiscoveryError(f"{argv[0]} exited {completed.returncode}: {message}")
    return completed.stdout


def _mib_to_bytes(value: str) -> int:
    return int(float(value.strip()) * 1024 * 1024)


def _split_csv(line: str) -> list[str]:
    return [item.strip() for item in line.split(",")]


def nvidia_smi_available() -> bool:
    return shutil.which("nvidia-smi") is not None


def discover_gpus() -> tuple[GPUDevice, ...]:
    if not nvidia_smi_available():
        return ()
    fields = (
        "index,name,uuid,memory.total,driver_version,compute_cap,pci.bus_id,"
        "memory.used,utilization.gpu,temperature.gpu"
    )
    output = _run(("nvidia-smi", f"--query-gpu={fields}", "--format=csv,noheader,nounits"))
    gpus: list[GPUDevice] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        values = _split_csv(line)
        if len(values) < 10:
            continue
        index, name, uuid, total, driver, compute_cap, pci, _used, _util, _temp = values[:10]
        try:
            gpus.append(
                GPUDevice(
                    uuid=uuid,
                    index=int(index),
                    name=name,
                    vram_total_bytes=_mib_to_bytes(total),
                    driver_version=driver or None,
                    compute_capability=compute_cap or None,
                    pci_bus_id=pci or None,
                    owned_by_lab=True,
                )
            )
        except (ValueError, TypeError):
            continue
    return tuple(gpus)


def cuda_driver_version() -> str | None:
    if not nvidia_smi_available():
        return None
    try:
        output = _run(("nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"))
    except HardwareDiscoveryError:
        return None
    first = output.splitlines()[0].strip() if output.splitlines() else ""
    return first or None


@dataclass(frozen=True)
class ExternalProcess:
    pid: int
    name: str
    used_memory_bytes: int


def external_compute_processes(settings: WorkerSettings) -> tuple[ExternalProcess, ...]:
    if not nvidia_smi_available():
        return ()
    try:
        output = _run(
            (
                "nvidia-smi",
                "--query-compute-apps=pid,process_name,used_memory",
                "--format=csv,noheader,nounits",
            )
        )
    except HardwareDiscoveryError:
        return ()
    allowed = set(settings.external_compute_process_allowlist)
    processes: list[ExternalProcess] = []
    for line in output.splitlines():
        values = _split_csv(line)
        if len(values) < 3:
            continue
        try:
            pid = int(values[0])
        except ValueError:
            continue
        name = Path(values[1]).name
        if name in allowed:
            continue
        try:
            used = _mib_to_bytes(values[2])
        except ValueError:
            used = 0
        processes.append(ExternalProcess(pid=pid, name=name, used_memory_bytes=used))
    return tuple(processes)


def contamination_warnings(settings: WorkerSettings) -> tuple[str, ...]:
    warnings: list[str] = []
    external = external_compute_processes(settings)
    if external:
        text = ", ".join(f"{item.name}:{item.pid}" for item in external)
        warnings.append(f"EXTERNAL_GPU_COMPUTE_PROCESS:{text}")
    try:
        usage = gpu_usage()
    except HardwareDiscoveryError:
        usage = []
    for gpu_uuid, used, total, util, temp in usage:
        if total and used / total > 0.5:
            warnings.append(f"GPU_MEMORY_BUSY:{gpu_uuid}:{round(used / total * 100)}%")
        if util > settings.max_gpu_utilization_pct:
            warnings.append(f"GPU_UTILIZATION_BUSY:{gpu_uuid}:{util}%")
        if temp > settings.max_gpu_temperature_c:
            warnings.append(f"GPU_HOT:{gpu_uuid}:{temp}C")
    return tuple(dict.fromkeys(warnings))


def gpu_usage() -> list[tuple[str, int, int, int, float]]:
    if not nvidia_smi_available():
        return []
    output = _run(
        (
            "nvidia-smi",
            "--query-gpu=uuid,memory.used,memory.total,utilization.gpu,temperature.gpu",
            "--format=csv,noheader,nounits",
        )
    )
    rows: list[tuple[str, int, int, int, float]] = []
    for line in output.splitlines():
        values = _split_csv(line)
        if len(values) < 5:
            continue
        try:
            rows.append(
                (
                    values[0],
                    _mib_to_bytes(values[1]),
                    _mib_to_bytes(values[2]),
                    int(float(values[3])),
                    float(values[4]),
                )
            )
        except ValueError:
            continue
    return rows


def collect_hardware(settings: WorkerSettings, *, hostname: str | None = None) -> HardwareSnapshot:
    memory = psutil.virtual_memory()
    cpu_model = platform.processor().strip()
    if not cpu_model:
        try:
            cpu_model = _run(("lscpu",)).split("Model name:", 1)[1].splitlines()[0].strip()
        except (IndexError, HardwareDiscoveryError):
            cpu_model = platform.machine() or "unknown CPU"
    warnings = contamination_warnings(settings)
    return HardwareSnapshot(
        hostname=hostname or socket.gethostname() or "localhost",
        os=f"{platform.system()} {platform.release()}",
        kernel=platform.release(),
        cpu_model=cpu_model[:200],
        cpu_threads=max(1, psutil.cpu_count(logical=True) or 1),
        ram_total_bytes=int(memory.total),
        ram_available_bytes=int(memory.available),
        gpus=discover_gpus(),
        cuda_driver_version=cuda_driver_version(),
        collected_at=utcnow(),
        contamination_warnings=warnings,
    )


@dataclass
class TelemetrySample:
    at: datetime
    gpu_uuid: str | None = None
    vram_used_bytes: int = 0
    gpu_utilization_pct: float = 0.0
    gpu_temperature_c: float = 0.0
    power_w: float | None = None
    sm_clock_mhz: int | None = None
    mem_clock_mhz: int | None = None
    system_ram_available_bytes: int = 0
    process_rss_bytes: int = 0


@dataclass
class TelemetrySummary:
    samples: list[TelemetrySample] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def vram_peak_bytes(self) -> int | None:
        values = [item.vram_used_bytes for item in self.samples if item.vram_used_bytes]
        return max(values) if values else None

    @property
    def ram_min_bytes(self) -> int | None:
        values = [item.system_ram_available_bytes for item in self.samples if item.system_ram_available_bytes]
        return min(values) if values else None

    @property
    def rss_peak_bytes(self) -> int | None:
        values = [item.process_rss_bytes for item in self.samples if item.process_rss_bytes]
        return max(values) if values else None

    @property
    def temperature_max_c(self) -> float | None:
        values = [item.gpu_temperature_c for item in self.samples if item.gpu_temperature_c]
        return max(values) if values else None

    @property
    def utilization_avg(self) -> float | None:
        values = [item.gpu_utilization_pct for item in self.samples if item.gpu_utilization_pct]
        return sum(values) / len(values) if values else None

    @property
    def power_avg_w(self) -> float | None:
        values = [item.power_w for item in self.samples if item.power_w is not None]
        return sum(values) / len(values) if values else None

    @property
    def sm_clock_max_mhz(self) -> int | None:
        values = [item.sm_clock_mhz for item in self.samples if item.sm_clock_mhz is not None]
        return max(values) if values else None

    @property
    def mem_clock_max_mhz(self) -> int | None:
        values = [item.mem_clock_mhz for item in self.samples if item.mem_clock_mhz is not None]
        return max(values) if values else None

    def coverage(self) -> float:
        return 1.0 if self.samples and not self.errors else (0.75 if self.samples else 0.0)


def sample_gpu(gpu_uuid: str | None, pid: int | None = None) -> TelemetrySample:
    now = datetime.now(UTC)
    vram = 0
    util = 0.0
    temp = 0.0
    power: float | None = None
    sm: int | None = None
    mem: int | None = None
    if gpu_uuid and nvidia_smi_available():
        try:
            output = _run(
                (
                    "nvidia-smi",
                    "--query-gpu=memory.used,utilization.gpu,temperature.gpu,power.draw,clocks.sm,clocks.mem",
                    "--format=csv,noheader,nounits",
                    "-i",
                    gpu_uuid,
                ),
                timeout=5.0,
            )
            values = _split_csv(output.splitlines()[0]) if output.splitlines() else []
            if len(values) >= 6:
                vram = _mib_to_bytes(values[0])
                util = float(values[1])
                temp = float(values[2])
                power = float(values[3]) if values[3] not in {"[N/A]", "N/A"} else None
                sm = int(float(values[4])) if values[4] not in {"[N/A]", "N/A"} else None
                mem = int(float(values[5])) if values[5] not in {"[N/A]", "N/A"} else None
        except (HardwareDiscoveryError, ValueError, IndexError):
            pass
    rss = 0
    if pid is not None:
        try:
            proc = psutil.Process(pid)
            rss = proc.memory_info().rss
            for child in proc.children(recursive=True):
                try:
                    rss += child.memory_info().rss
                except psutil.Error:
                    continue
        except psutil.Error:
            rss = 0
    return TelemetrySample(
        at=now,
        gpu_uuid=gpu_uuid,
        vram_used_bytes=vram,
        gpu_utilization_pct=util,
        gpu_temperature_c=temp,
        power_w=power,
        sm_clock_mhz=sm,
        mem_clock_mhz=mem,
        system_ram_available_bytes=int(psutil.virtual_memory().available),
        process_rss_bytes=rss,
    )


def gpu_preflight(settings: WorkerSettings, gpu_uuid: str) -> tuple[bool, tuple[str, ...]]:
    """Check whether a GPU is safe to lease without touching foreign processes."""
    reasons: list[str] = []
    usage = {row[0]: row for row in gpu_usage()}
    row = usage.get(gpu_uuid)
    if row is None:
        return False, (f"GPU_NOT_PRESENT:{gpu_uuid}",)
    _uuid, used, total, util, temp = row
    if total - used < settings.min_free_vram_bytes:
        reasons.append(f"INSUFFICIENT_FREE_VRAM:{total - used}<{settings.min_free_vram_bytes}")
    if util > settings.max_gpu_utilization_pct:
        reasons.append(f"GPU_UTILIZATION_BUSY:{util}>{settings.max_gpu_utilization_pct}")
    if temp > settings.max_gpu_temperature_c:
        reasons.append(f"GPU_TOO_HOT:{temp}>{settings.max_gpu_temperature_c}")
    external = external_compute_processes(settings)
    if external:
        reasons.append("EXTERNAL_GPU_COMPUTE:" + ",".join(f"{item.name}:{item.pid}" for item in external))
    return not reasons, tuple(reasons)


def uptime_seconds() -> float | None:
    try:
        return float(psutil.boot_time())
    except (psutil.Error, ValueError):
        return None


def process_start_ticks(pid: int) -> int | None:
    try:
        return int(psutil.Process(pid).create_time() * 1_000_000)
    except psutil.Error:
        return None


def process_is_alive(pid: int, expected_start_ticks: int | None = None) -> bool:
    try:
        proc = psutil.Process(pid)
        if expected_start_ticks is not None:
            current = int(proc.create_time() * 1_000_000)
            if abs(current - expected_start_ticks) > 2_000_000:
                return False
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value
