"""Read-only model discovery, GGUF metadata parsing and strong file hashing.

Discovery never writes to a model root. The SHA-256 cache records
``(size, mtime_ns)`` and is invalidated when either changes. Everything the
worker reports is derived from observed files or metadata; unknown fields are
left unknown instead of guessed.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from lab_core.ids import sha256_hex, sha256_text

from lab_core import EngineId, ModelArtifact, ModelFile

from .config import WorkerSettings

_QUANT_RE = re.compile(
    r"(?i)(?:^|[-_.])(IQ[0-9]_[A-Z0-9]+|Q[0-9]_[A-Z0-9]+|Q[0-9]_[0-9]|F16|BF16|F32|FP16|FP32)(?:$|[-_.])"
)
_SHARD_RE = re.compile(r"^(?P<base>.+)-(?P<index>\d{5})-of-(?P<count>\d{5})\.gguf$", re.IGNORECASE)
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


class ModelDiscoveryError(RuntimeError):
    pass


@dataclass
class FileDigest:
    sha256: str
    size_bytes: int
    mtime_ns: int


class ModelVerificationCancelled(RuntimeError):
    pass


class HashCache:
    """Persistent SHA-256 cache for large read-only model files."""

    def __init__(
        self,
        path: Path,
        *,
        hash_paths: frozenset[str] | None = None,
        progress: bool = False,
        model_id: str | None = None,
        cancelled: Callable[[], bool] | None = None,
    ) -> None:
        self.path = path
        self.hash_paths = hash_paths
        self.progress = progress
        self.model_id = model_id
        self.cancelled = cancelled
        self.completed: set[str] = set()
        self.bytes_done = 0
        self.last_progress = 0.0
        self.current_file = ""
        self.total_bytes = sum(
            Path(item).stat().st_size for item in (hash_paths or ()) if Path(item).is_file()
        )
        self._entries: dict[str, FileDigest] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        for key, value in payload.items():
            if not isinstance(key, str) or not isinstance(value, dict):
                continue
            sha = value.get("sha256")
            size = value.get("size_bytes")
            mtime = value.get("mtime_ns")
            if (
                isinstance(sha, str)
                and re.fullmatch(r"[0-9a-f]{64}", sha)
                and isinstance(size, int)
                and isinstance(mtime, int)
            ):
                self._entries[key] = FileDigest(sha256=sha, size_bytes=size, mtime_ns=mtime)

    def flush(self) -> None:
        if not self._dirty:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        payload = {
            key: {
                "sha256": value.sha256,
                "size_bytes": value.size_bytes,
                "mtime_ns": value.mtime_ns,
            }
            for key, value in self._entries.items()
        }
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with temp.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp, self.path)
        with self.path.open("rb") as handle:
            os.fsync(handle.fileno())
        self._dirty = False

    def lookup(self, path: Path) -> FileDigest | None:
        stat = path.stat()
        if not path.is_file() or not os.access(path, os.R_OK):
            return None
        cached = self._entries.get(str(path))
        return (
            cached
            if cached and cached.size_bytes == stat.st_size and cached.mtime_ns == stat.st_mtime_ns
            else None
        )

    def report(self, state: str, *, file: str = "", partial: int = 0, force: bool = False) -> None:
        if not self.progress or (not force and time.monotonic() - self.last_progress < 0.5):
            return
        self.last_progress = time.monotonic()
        if file:
            self.current_file = file
        value = {
            "state": state,
            "model_id": self.model_id,
            "bytes_done": self.bytes_done + partial,
            "bytes_total": self.total_bytes,
            "files_done": len(self.completed),
            "files_total": len(self.hash_paths or ()),
            "current_file": Path(self.current_file).name,
            "current_path": self.current_file,
            "updated_at": time.time(),
        }
        target = self.path.with_name("verification-progress.json")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(value))
            temporary.chmod(0o600)
            temporary.replace(target)
        except OSError:
            pass  # Display progress must never affect identity verification.

    def model_digest(self, path: Path, hashing: bool) -> FileDigest | None:
        if not hashing or (self.hash_paths is not None and str(path) not in self.hash_paths):
            return self.lookup(path)
        value = self.digest(path)
        if str(path) not in self.completed:
            self.flush()
            self.completed.add(str(path))
            self.bytes_done += value.size_bytes
            self.report("verifying", force=True)
        return value

    def digest(self, path: Path) -> FileDigest:
        if self.cancelled and self.cancelled():
            raise ModelVerificationCancelled(
                "Model verification interrupted by shutdown; cached files are preserved"
            )
        stat = path.stat()
        key = str(path)
        cached = self.lookup(path)
        if cached:
            return cached
        digest = hashlib.sha256()
        partial = 0
        with path.open("rb") as handle:
            while chunk := handle.read(8 * 1024 * 1024):
                if self.cancelled and self.cancelled():
                    raise ModelVerificationCancelled(
                        "Model verification interrupted by shutdown; cached files are preserved"
                    )
                digest.update(chunk)
                partial += len(chunk)
                self.report("verifying", file=str(path), partial=partial)
        after = path.stat()
        if after.st_size != stat.st_size or after.st_mtime_ns != stat.st_mtime_ns:
            raise ModelDiscoveryError(f"model file changed while hashing: {path}")
        value = FileDigest(
            sha256=digest.hexdigest(),
            size_bytes=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
        )
        self._entries[key] = value
        self._dirty = True
        return value


@dataclass
class GgufMetadata:
    version: int
    tensor_count: int
    values: dict[str, Any] = field(default_factory=dict)
    architecture: str | None = None
    name: str | None = None
    context_length: int | None = None
    parameter_count: int | None = None
    tokenizer_model: str | None = None

    @property
    def moe(self) -> bool:
        keys = (self.architecture or "").lower()
        return "moe" in keys or "expert" in self.values.get("general.name", "").lower()


_GGUF_MAGIC = b"GGUF"
_GGUF_SCALAR: dict[int, tuple[str, int]] = {
    0: ("<B", 1),
    1: ("<b", 1),
    2: ("<H", 2),
    3: ("<h", 2),
    4: ("<I", 4),
    5: ("<i", 4),
    6: ("<f", 4),
    7: ("<?", 1),
    10: ("<Q", 8),
    11: ("<q", 8),
    12: ("<d", 8),
}
_MAX_STRING = 64 * 1024 * 1024


def _read_exact(handle: Any, count: int) -> bytes:
    data = handle.read(count)
    if len(data) != count:
        raise ModelDiscoveryError("truncated GGUF metadata")
    return bytes(data)


def _read_string(handle: Any) -> str:
    (length,) = struct.unpack("<Q", _read_exact(handle, 8))
    if length > _MAX_STRING:
        raise ModelDiscoveryError(f"GGUF string length is implausibly large: {length}")
    return _read_exact(handle, length).decode("utf-8", "replace")


def _skip_value(handle: Any, value_type: int) -> None:
    scalar = _GGUF_SCALAR.get(value_type)
    if scalar is not None:
        handle.seek(scalar[1], os.SEEK_CUR)
        return
    if value_type == 8:
        (length,) = struct.unpack("<Q", _read_exact(handle, 8))
        if length > _MAX_STRING:
            raise ModelDiscoveryError("GGUF metadata string is too large")
        handle.seek(length, os.SEEK_CUR)
        return
    if value_type == 9:
        (item_type,) = struct.unpack("<I", _read_exact(handle, 4))
        (count,) = struct.unpack("<Q", _read_exact(handle, 8))
        if count > 100_000_000:
            raise ModelDiscoveryError("GGUF metadata array is too large")
        scalar = _GGUF_SCALAR.get(item_type)
        if scalar is not None:
            handle.seek(scalar[1] * count, os.SEEK_CUR)
            return
        if item_type == 8:
            for _ in range(count):
                (length,) = struct.unpack("<Q", _read_exact(handle, 8))
                handle.seek(length, os.SEEK_CUR)
            return
        if item_type == 9:
            for _ in range(count):
                _skip_value(handle, 9)
            return
        raise ModelDiscoveryError(f"unsupported GGUF array item type {item_type}")
    raise ModelDiscoveryError(f"unsupported GGUF metadata type {value_type}")


def _read_value(handle: Any, value_type: int) -> Any:
    scalar = _GGUF_SCALAR.get(value_type)
    if scalar is not None:
        fmt, size = scalar
        return struct.unpack(fmt, _read_exact(handle, size))[0]
    if value_type == 8:
        return _read_string(handle)
    if value_type == 9:
        (item_type,) = struct.unpack("<I", _read_exact(handle, 4))
        (count,) = struct.unpack("<Q", _read_exact(handle, 8))
        if item_type in _GGUF_SCALAR and count <= 1024:
            fmt, size = _GGUF_SCALAR[item_type]
            return [struct.unpack(fmt, _read_exact(handle, size))[0] for _ in range(count)]
        for _ in range(count):
            _skip_value(handle, item_type)
        return {"array_length": count, "item_type": item_type}
    raise ModelDiscoveryError(f"unsupported GGUF metadata type {value_type}")


def read_gguf_metadata(path: Path, *, max_pairs: int = 100_000) -> GgufMetadata:
    with path.open("rb") as handle:
        if _read_exact(handle, 4) != _GGUF_MAGIC:
            raise ModelDiscoveryError(f"{path} is not a GGUF file")
        (version,) = struct.unpack("<I", _read_exact(handle, 4))
        if version not in (2, 3):
            raise ModelDiscoveryError(f"unsupported GGUF version {version} in {path}")
        (tensor_count,) = struct.unpack("<Q", _read_exact(handle, 8))
        (pair_count,) = struct.unpack("<Q", _read_exact(handle, 8))
        if pair_count > max_pairs:
            raise ModelDiscoveryError(f"implausible GGUF metadata pair count {pair_count}")
        values: dict[str, Any] = {}
        for _ in range(pair_count):
            key = _read_string(handle)
            (value_type,) = struct.unpack("<I", _read_exact(handle, 4))
            values[key] = _read_value(handle, value_type)
    architecture = values.get("general.architecture")
    if not isinstance(architecture, str):
        architecture = None
    metadata = GgufMetadata(
        version=version,
        tensor_count=tensor_count,
        values=values,
        architecture=architecture,
        name=values.get("general.name") if isinstance(values.get("general.name"), str) else None,
        tokenizer_model=values.get("tokenizer.ggml.model")
        if isinstance(values.get("tokenizer.ggml.model"), str)
        else None,
    )
    if architecture:
        context = values.get(f"{architecture}.context_length")
        if isinstance(context, (int, float)) and context > 0:
            metadata.context_length = int(context)
        parameters = values.get(f"{architecture}.parameter_count")
        if isinstance(parameters, (int, float)) and parameters > 0:
            metadata.parameter_count = int(parameters)
    return metadata


def _quantization(name: str) -> str | None:
    match = _QUANT_RE.search(name)
    if not match:
        return None
    return match.group(1).upper().replace("FP16", "F16").replace("FP32", "F32")


def _safe_id(value: str) -> str:
    cleaned = _SAFE_ID_RE.sub("-", value).strip("-_.:")
    cleaned = cleaned[:110] or "model"
    return cleaned


def _within(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve(strict=False)
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _walk_files(root: Path, *, max_depth: int, follow_symlinks: bool) -> list[Path]:
    files: list[Path] = []
    root_depth = len(root.parts)
    for current, directories, names in os.walk(root, followlinks=follow_symlinks):
        current_path = Path(current)
        depth = len(current_path.parts) - root_depth
        directories[:] = [
            item
            for item in directories
            if not item.startswith(".")
            and item not in {"node_modules", "__pycache__", "attic"}
            and depth < max_depth
        ]
        if depth >= max_depth:
            directories[:] = []
        for name in names:
            if name.startswith("."):
                continue
            files.append(current_path / name)
    return files


def _group_ggufs(paths: list[Path]) -> dict[str, list[tuple[int, int, Path]]]:
    groups: dict[str, list[tuple[int, int, Path]]] = {}
    for path in paths:
        if path.suffix.lower() != ".gguf":
            continue
        if "mmproj" in path.name.lower() or path.name.lower().startswith("mtp-"):
            continue
        match = _SHARD_RE.match(path.name)
        if match:
            key = str(path.parent / match.group("base"))
            groups.setdefault(key, []).append((int(match.group("index")), int(match.group("count")), path))
        else:
            groups.setdefault(str(path), []).append((1, 1, path))
    return groups


def discover_llamacpp_models(
    settings: WorkerSettings,
    *,
    cache: HashCache,
    roots: tuple[Path, ...] | None = None,
    warnings: list[str] | None = None,
    hash_models: bool | None = None,
) -> tuple[ModelArtifact, ...]:
    warnings = warnings if warnings is not None else []
    roots = roots or settings.resolved_model_roots
    hashing = settings.hashing_enabled if hash_models is None else hash_models
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            warnings.append(f"MODEL_ROOT_MISSING:{root}")
            continue
        try:
            files.extend(
                _walk_files(root, max_depth=settings.max_scan_depth, follow_symlinks=settings.follow_symlinks)
            )
        except OSError as exc:
            warnings.append(f"MODEL_ROOT_UNREADABLE:{root}:{type(exc).__name__}")
    groups = _group_ggufs(files)
    models: list[ModelArtifact] = []
    used_ids: set[str] = set()
    for key, shards in sorted(groups.items()):
        shards = sorted(shards)
        if len(shards) > settings.max_model_files:
            warnings.append(f"MODEL_SHARD_LIMIT:{key}:{len(shards)}")
            continue
        first = shards[0][2]
        metadata: GgufMetadata | None = None
        try:
            metadata = read_gguf_metadata(first)
        except (OSError, ModelDiscoveryError) as exc:
            warnings.append(f"GGUF_METADATA_UNREADABLE:{first.name}:{type(exc).__name__}")
        relative = first.relative_to(next((root for root in roots if _within(first, (root,))), first.parent))
        base_id = _safe_id(str(relative.with_suffix("")))
        model_id = base_id
        counter = 2
        while model_id in used_ids:
            model_id = _safe_id(f"{base_id}-{counter}")
            counter += 1
        used_ids.add(model_id)
        model_files: list[ModelFile] = []
        total = 0
        verified = True
        for index, count, path in shards:
            try:
                size = path.stat().st_size
                digest = cache.model_digest(path, hashing)
            except (OSError, ModelDiscoveryError) as exc:
                warnings.append(f"MODEL_HASH_FAILED:{path.name}:{type(exc).__name__}")
                verified = False
                size = 0
                digest = None
            total += size
            model_files.append(
                ModelFile(
                    path=str(path),
                    sha256=digest.sha256 if digest else None,
                    size_bytes=size,
                    verified=bool(digest),
                    shard_index=index if count > 1 else None,
                    shard_count=count if count > 1 else None,
                )
            )
        if not all(item.verified for item in model_files):
            verified = False
        architecture = metadata.architecture if metadata and metadata.architecture else "gguf"
        quantization = _quantization(first.name)
        models.append(
            ModelArtifact(
                model_id=model_id,
                display_name=(metadata.name if metadata and metadata.name else first.stem)[:200],
                architecture=architecture,
                model_family=architecture,
                quantization=quantization,
                files=tuple(model_files),
                path_map=(str(first),),
                tokenizer_id=metadata.tokenizer_model if metadata else None,
                metadata_context_tokens=metadata.context_length if metadata else None,
                parameter_count=metadata.parameter_count if metadata else None,
                size_bytes=total,
                verified=verified,
                compatible_engines=(EngineId.LLAMACPP,),
                metadata={
                    "format": "gguf",
                    "gguf_version": metadata.version if metadata else None,
                    "tensor_count": metadata.tensor_count if metadata else None,
                    "moe": metadata.moe if metadata else False,
                    "discovered_by": "lab-worker",
                },
            )
        )
    return tuple(models)


def _strata_pack_dirs(settings: WorkerSettings, roots: tuple[Path, ...], warnings: list[str]) -> list[Path]:
    packs: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        try:
            candidates = [item for item in root.rglob("packs") if item.is_dir()]
        except OSError:
            continue
        for packs_dir in candidates:
            try:
                children = sorted(packs_dir.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if not (child / "index.txt").is_file():
                    continue
                if not ((child / "dense.bin").is_file() or (child / "experts.bin").is_file()):
                    continue
                packs.append(child)
                if len(packs) >= settings.max_strata_packs:
                    warnings.append("STRATA_PACK_LIMIT_REACHED")
                    return packs
    return packs


def _strata_source_shards(pack: Path) -> list[tuple[str, int]]:
    """Read the read-only source-shard identity emitted by the pack tool."""

    try:
        payload = json.loads((pack / "conversions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, dict):
        return []
    shards = payload.get("source_shards")
    if not isinstance(shards, list):
        return []
    result: list[tuple[str, int]] = []
    for item in shards:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        size = item.get("size")
        if isinstance(name, str) and name and isinstance(size, int) and size > 0:
            result.append((name, size))
    return result


def _index_gguf_paths(
    settings: WorkerSettings, roots: tuple[Path, ...], warnings: list[str]
) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for root in roots:
        if not root.is_dir():
            continue
        try:
            paths = _walk_files(
                root,
                max_depth=settings.max_scan_depth,
                follow_symlinks=settings.follow_symlinks,
            )
        except OSError as exc:
            warnings.append(f"STRATA_SOURCE_SCAN_FAILED:{root}:{type(exc).__name__}")
            continue
        for path in paths:
            if path.suffix.lower() != ".gguf" or "mmproj" in path.name.lower():
                continue
            index.setdefault(path.name, []).append(path)
    return index


def _resolve_strata_source_shards(
    pack: Path,
    *,
    sources: list[tuple[str, int]],
    gguf_index: dict[str, list[Path]],
    roots: tuple[Path, ...],
    warnings: list[str],
) -> list[tuple[Path, int, int]] | None:
    """Resolve every source shard without writing to the model tree.

    The pack's ``native_experts.txt`` offsets are relative to the first source
    GGUF, so that path is emitted first. We require an exact basename and size
    match for every shard before handing any path to the engine; an ambiguous,
    missing or changed file is a hard refusal, not a guess.
    """

    if not sources:
        warnings.append(f"STRATA_SOURCE_SHARDS_MISSING:{pack.name}")
        return None
    resolved: list[tuple[Path, int, int]] = []
    for index, (name, expected_size) in enumerate(sources, start=1):
        candidates = sorted(gguf_index.get(name, ()))
        candidates = [path for path in candidates if _within(path, roots)]
        if not candidates:
            warnings.append(f"STRATA_NATIVE_SHARD_NOT_FOUND:{pack.name}:{name}")
            return None
        if len(candidates) > 1:
            warnings.append(f"STRATA_NATIVE_SHARD_AMBIGUOUS:{pack.name}:{name}:{len(candidates)}")
            return None
        path = candidates[0]
        try:
            size = path.stat().st_size
        except OSError:
            warnings.append(f"STRATA_NATIVE_SHARD_UNREADABLE:{pack.name}:{name}")
            return None
        if size != expected_size:
            warnings.append(f"STRATA_NATIVE_SHARD_SIZE_MISMATCH:{pack.name}:{name}:{size}!={expected_size}")
            return None
        resolved.append((path, size, index))
    return resolved


def discover_strata_models(
    settings: WorkerSettings,
    *,
    cache: HashCache,
    roots: tuple[Path, ...] | None = None,
    warnings: list[str] | None = None,
    hash_models: bool | None = None,
) -> tuple[ModelArtifact, ...]:
    warnings = warnings if warnings is not None else []
    roots = roots or settings.resolved_model_roots
    hashing = settings.hashing_enabled if hash_models is None else hash_models
    gguf_index = _index_gguf_paths(settings, roots, warnings)
    models: list[ModelArtifact] = []
    used_ids: set[str] = set()
    for pack in _strata_pack_dirs(settings, roots, warnings):
        parent = pack.parent.parent.name if pack.parent.name == "packs" else pack.parent.name
        base_id = _safe_id(f"{parent}-{pack.name}")
        model_id = base_id
        counter = 2
        while model_id in used_ids:
            model_id = _safe_id(f"{base_id}-{counter}")
            counter += 1
        used_ids.add(model_id)
        files: list[ModelFile] = []
        total = 0
        verified = True
        tokenizer = next(
            (candidate for candidate in (pack / "tokenizer", pack / "tokenizer.json") if candidate.exists()),
            None,
        )
        include = ["index.txt", "conversions.json", "native_experts.txt"]
        if tokenizer is not None and tokenizer.is_dir():
            include.extend(str(item.relative_to(pack)) for item in tokenizer.rglob("*") if item.is_file())
        candidates = [pack / item for item in include] + [
            path for path in (pack / "dense.bin", pack / "experts.bin") if path.is_file()
        ]
        for path in candidates:
            if not path.is_file():
                continue
            try:
                size = path.stat().st_size
                digest = cache.model_digest(path, hashing)
            except (OSError, ModelDiscoveryError) as exc:
                warnings.append(f"STRATA_HASH_FAILED:{path.name}:{type(exc).__name__}")
                verified = False
                size = 0
                digest = None
            total += size
            files.append(
                ModelFile(
                    path=str(path),
                    sha256=digest.sha256 if digest else None,
                    size_bytes=size,
                    verified=bool(digest),
                )
            )
        if not any(item.path.endswith(("dense.bin", "experts.bin")) for item in files):
            continue
        source_shards = _strata_source_shards(pack)
        resolved_shards = _resolve_strata_source_shards(
            pack,
            sources=source_shards,
            gguf_index=gguf_index,
            roots=roots,
            warnings=warnings,
        )
        native_path: Path | None = None
        native_sha256: str | None = None
        native_size: int | None = None
        if resolved_shards is not None:
            native_path, native_size, _native_index = resolved_shards[0]
            for path, size, index in resolved_shards:
                try:
                    digest = cache.model_digest(path, hashing)
                except (OSError, ModelDiscoveryError) as exc:
                    warnings.append(f"STRATA_NATIVE_HASH_FAILED:{path.name}:{type(exc).__name__}")
                    digest = None
                    verified = False
                sha256 = digest.sha256 if digest else None
                if index == 1:
                    native_sha256 = sha256
                total += size
                files.append(
                    ModelFile(
                        path=str(path),
                        sha256=sha256,
                        size_bytes=size,
                        verified=bool(sha256),
                        shard_index=index if len(resolved_shards) > 1 else None,
                        shard_count=len(resolved_shards) if len(resolved_shards) > 1 else None,
                    )
                )
        if not all(item.verified for item in files):
            verified = False
        metadata = {
            "model_type": "strata-pack",
            "pack_path": str(pack),
            "native": True,
            "native_shard": str(native_path) if native_path is not None else None,
            "native_shard_sha256": native_sha256,
            "native_shard_size_bytes": native_size,
            "source_shards": [{"name": name, "size": size} for name, size in source_shards],
            "tokenizer_path": str(tokenizer) if tokenizer is not None else None,
            "server_script": settings.strata_server_script,
            "engine_executable": settings.strata_path,
            "engine_sha256": None,
            "backend": "cuda",
            "moe": True,
            "format": "strata-pack",
            "discovered_by": "lab-worker",
        }
        models.append(
            ModelArtifact(
                model_id=model_id,
                display_name=f"Strata {parent} {pack.name}"[:200],
                architecture="strata-pack",
                model_family="strata",
                quantization=_quantization(pack.name),
                files=tuple(files),
                path_map=(str(pack),),
                tokenizer_id="strata-pack",
                metadata_context_tokens=None,
                size_bytes=total,
                verified=verified,
                compatible_engines=(EngineId.STRATA,),
                metadata=metadata,
            )
        )
    return tuple(models)


def discover_models(
    settings: WorkerSettings,
    *,
    roots: tuple[Path, ...] | None = None,
    warnings: list[str] | None = None,
    hash_models: bool | None = None,
    hash_paths: frozenset[str] | None = None,
    model_id: str | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ModelArtifact, ...]:
    settings.ensure_directories()
    cache = HashCache(
        settings.resolved_hash_cache,
        hash_paths=hash_paths,
        progress=bool(hash_models),
        model_id=model_id,
        cancelled=cancelled,
    )
    cache.report("verifying", force=True)
    warnings = warnings if warnings is not None else []
    models: list[ModelArtifact] = []
    completed_scan = False
    try:
        models.extend(
            discover_llamacpp_models(
                settings, cache=cache, roots=roots, warnings=warnings, hash_models=hash_models
            )
        )
        models.extend(
            discover_strata_models(
                settings, cache=cache, roots=roots, warnings=warnings, hash_models=hash_models
            )
        )
        completed_scan = True
    finally:
        try:
            cache.flush()
            complete = completed_scan and all(model.verified for model in models)
            for item in hash_paths or ():
                try:
                    if cache.lookup(Path(item)) is None:
                        complete = False
                except OSError:
                    complete = False
            cache.report("complete" if complete else "failed", force=True)
        except OSError as exc:
            warnings.append(f"HASH_CACHE_WRITE_FAILED:{type(exc).__name__}")
            cache.report("failed", force=True)
    return tuple(models)


def model_digest_summary(models: tuple[ModelArtifact, ...]) -> str:
    return sha256_hex([item.artifact_digest for item in sorted(models, key=lambda item: item.model_id)])


def public_model_paths(models: tuple[ModelArtifact, ...]) -> tuple[str, ...]:
    return tuple(item.path_map[0] for item in models if item.path_map)


def manifest_digest(values: tuple[str, ...]) -> str:
    return sha256_text("\n".join(values))
