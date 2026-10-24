"""Read-only desktop compatibility facts; never execute an engine or change drivers."""

from __future__ import annotations

import ctypes
import json
import platform
from pathlib import Path
from typing import Any

from .hardware import discover_gpus


def vulkan_devices() -> list[dict[str, Any]]:
    """Ask the installed Vulkan loader for physical devices; no rendering/context work."""

    class CreateInfo(ctypes.Structure):
        _fields_ = [
            ("sType", ctypes.c_uint32),
            ("pNext", ctypes.c_void_p),
            ("flags", ctypes.c_uint32),
            ("app", ctypes.c_void_p),
            ("layerCount", ctypes.c_uint32),
            ("layers", ctypes.c_void_p),
            ("extensionCount", ctypes.c_uint32),
            ("extensions", ctypes.c_void_p),
        ]

    loader = ctypes.CDLL("libvulkan.so.1")
    instance = ctypes.c_void_p()
    loader.vkCreateInstance.argtypes = [
        ctypes.POINTER(CreateInfo),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    loader.vkDestroyInstance.restype = None
    loader.vkGetPhysicalDeviceProperties.restype = None
    loader.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    loader.vkEnumeratePhysicalDevices.argtypes = [
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    ]
    loader.vkGetPhysicalDeviceProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    if loader.vkCreateInstance(ctypes.byref(CreateInfo(sType=1)), None, ctypes.byref(instance)) != 0:
        return []
    try:
        count = ctypes.c_uint32()
        if (
            loader.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None) != 0
            or not 0 < count.value <= 32
        ):
            return []
        devices = (ctypes.c_void_p * count.value)()
        if loader.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), devices) != 0:
            return []
        found = []
        for device in devices[: count.value]:
            properties = ctypes.create_string_buffer(4096)
            loader.vkGetPhysicalDeviceProperties(device, properties)
            header = (ctypes.c_uint32 * 5).from_buffer(properties)
            if header[4] not in (1, 2, 3):  # Exclude CPU/software ICDs.
                continue
            vendor = {0x10DE: "nvidia", 0x1002: "amd", 0x8086: "intel"}.get(header[2], "other")
            found.append(
                {
                    "vendor": vendor,
                    "name": properties.raw[20:276].split(b"\0")[0].decode(errors="replace"),
                    "vulkan_version": f"{header[0] >> 22}.{(header[0] >> 12) & 1023}",
                    "device_type": "discrete" if header[4] == 2 else "integrated",
                    "device_id": header[3],
                }
            )
        return found
    finally:
        loader.vkDestroyInstance(instance, None)


def collect_desktop_hardware() -> dict[str, Any]:
    gpus: list[dict[str, Any]] = []
    warnings: list[str] = []
    try:
        for device in discover_gpus():
            gpus.append(
                {
                    "vendor": "nvidia",
                    "name": device.name,
                    "driver_version": device.driver_version,
                    "compute_capability": device.compute_capability,
                    "vram_bytes": device.vram_total_bytes,
                    "device_type": "discrete",
                }
            )
    except Exception:
        warnings.append("NVIDIA driver information could not be read")
    try:
        for gpu in vulkan_devices():
            existing = next(
                (
                    item
                    for item in gpus
                    if item["name"].lower().replace("nvidia ", "")
                    == gpu["name"].lower().replace("nvidia ", "")
                ),
                None,
            )
            if existing:
                existing.update(vulkan_version=gpu["vulkan_version"])
            else:
                gpus.append(gpu)
    except Exception:
        warnings.append("Vulkan device information is unavailable")
    # KFD topology provides actual AMD architecture, rather than guessing from a product name.
    for properties in sorted(Path("/sys/class/kfd/kfd/topology/nodes").glob("*/properties"))[:32]:
        try:
            values = dict(
                line.split(maxsplit=1) for line in properties.read_text().splitlines() if " " in line
            )
            version = int(values.get("gfx_target_version", "0"))
            if not version:
                continue
            device_id = int(values.get("device_id", "0"))
            arch = f"gfx{version // 10000}{version % 10000 // 100}{version % 100}"
            matching = [
                gpu for gpu in gpus if gpu.get("vendor") == "amd" and gpu.get("device_id") == device_id
            ]
            if not matching:
                gpus.append(
                    {
                        "vendor": "amd",
                        "name": f"AMD {arch}",
                        "architecture": arch,
                        "device_type": "integrated" if arch == "gfx1151" else "discrete",
                    }
                )
            for gpu in matching:
                gpu["architecture"] = arch
        except (OSError, ValueError):
            continue
    try:
        flags = (
            Path("/proc/cpuinfo").read_text().split("flags", 1)[1].splitlines()[0].split(":", 1)[1].split()
        )
    except (OSError, IndexError):
        flags = []
    return {
        "architecture": platform.machine(),
        "gpus": gpus,
        "cpu_avx2": "avx2" in flags,
        "warnings": warnings,
        "source": "local driver queries",
    }


def main() -> None:
    print(json.dumps(collect_desktop_hardware()))
