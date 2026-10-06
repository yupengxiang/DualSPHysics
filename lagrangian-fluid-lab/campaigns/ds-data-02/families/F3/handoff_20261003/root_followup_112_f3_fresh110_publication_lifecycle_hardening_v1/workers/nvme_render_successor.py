#!/usr/bin/env python3
"""Root-owned NVMe staging successor for complete Root023 renders.

This module is deliberately independent of the historical F6 controller.  It
accepts an already-registered temporal XDMF manifest, invokes the approved
Root023 renderer in a private staging directory, and publishes only derived
render files after bounded stat/hash checks.  The wrapper never opens or
hashes BI4/H5/CSV/DAT/VTK payloads; ParaView performs that work only inside a
future, root-registered CPU task.  This fresh112 revision keeps own-process
cleanup installed through publication, treats the Home sibling as an owned
transaction, and rejects private stage/NVMe paths recursively in derived
JSON/PVSM while leaving registered trajectory H5 references untouched.

The source package ships disabled requests and toy tests.  ``execute_request``
requires an explicit root execution authorization and refuses disabled source
requests, so importing or preflighting this module cannot launch a renderer.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from typing import Any, Callable, Iterable, Mapping, Sequence


SCHEMA = "ds02.stage1.f3.fresh112.nvme-render-successor.v1"
REPORT_SCHEMA = "ds02.stage1.paraview-full-animation-integrity.v1"
GI = 1024 ** 3
DEFAULT_HOME_FLOOR = 500 * GI
DEFAULT_NVME_FLOOR = 100 * GI
DEFAULT_STAGE_CAP = 24 * GI
DEFAULT_HOME_CAP = 3 * GI
DEFAULT_RENDER_CAP = 2
DEFAULT_CPU_THREADS = 24
DEFAULT_ENV_THREADS = 2
FORBIDDEN_SUFFIXES = {
    ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu",
    ".npy", ".npz", ".raw", ".bin",
}
DERIVED_SUFFIXES = {".png", ".gif", ".pvsm", ".json", ".txt", ".log"}
HEX = set("0123456789abcdefABCDEF")


class ContractError(RuntimeError):
    """A bounded request or publication contract violation."""


def _absolute(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ContractError(f"{label} must be a non-empty path string")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ContractError(f"{label} must be absolute: {value!r}")
    return path


def _hex64(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or not set(value) <= HEX:
        raise ContractError(f"{label} must be a 64-character hexadecimal digest")
    return value


def _suffix(path: Path) -> str:
    return path.suffix.lower()


def _reject_payload_path(path: Path, label: str) -> None:
    if _suffix(path) in FORBIDDEN_SUFFIXES:
        raise ContractError(f"{label} points at a scientific payload: {path}")


def _sha256(path: Path) -> str:
    """Hash a derived metadata/render file only.

    Callers must reject forbidden suffixes before entering this function.
    """

    _reject_payload_path(path, "derived file")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _walk_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        raise ContractError(f"output directory does not exist: {root}")
    files: list[Path] = []
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                path = Path(entry.path)
                if entry.is_symlink():
                    raise ContractError(f"symlinks are forbidden in render output: {path}")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(path)
                elif entry.is_file(follow_symlinks=False):
                    _reject_payload_path(path, "render output")
                    if _suffix(path) not in DERIVED_SUFFIXES:
                        raise ContractError(f"unexpected render output suffix: {path}")
                    files.append(path)
                else:
                    raise ContractError(f"unsupported output filesystem entry: {path}")
    return sorted(files)


def _tree_bytes(root: Path) -> int:
    """Bounded stat-only size accounting; never reads file contents."""

    total = 0
    if not root.exists():
        return total
    stack = [root]
    while stack:
        current = stack.pop()
        with os.scandir(current) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise ContractError(f"symlinks are forbidden in staging: {entry.path}")
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
                else:
                    raise ContractError(f"unsupported staging filesystem entry: {entry.path}")
    return total


def _load_json(path: Path, label: str) -> dict[str, Any]:
    _reject_payload_path(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"{label} must contain a JSON object: {path}")
    return value


def _resolve_under(path: Path, root: Path, label: str) -> None:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError as exc:
        raise ContractError(f"{label} escapes its output root: {path}") from exc


def _replace_prefix(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        if value == old:
            return new
        if value.startswith(old + os.sep):
            return new + value[len(old):]
        return value
    if isinstance(value, list):
        return [_replace_prefix(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: _replace_prefix(item, old, new) for key, item in value.items()}
    return value


def _contains_path_component(value: str, root: Path) -> bool:
    """Return true when a serialized value contains root as a path component."""

    normalized = value.replace("\\", "/")
    root_text = str(root.resolve(strict=False)).replace("\\", "/").rstrip("/")
    return normalized == root_text or (root_text + "/") in normalized


def _iter_strings(value: Any, prefix: str = "$") -> Iterable[tuple[str, str]]:
    """Yield every JSON string, including object keys, without opening payloads."""

    if isinstance(value, str):
        yield prefix, value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _iter_strings(item, f"{prefix}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(key, str):
                yield f"{prefix}.<key>", key
            yield from _iter_strings(item, f"{prefix}.{key}")


def _reject_private_paths(value: Any, private_roots: Sequence[Path], label: str) -> None:
    """Reject private stage paths while preserving external trajectory H5 references."""

    hits = []
    for location, text in _iter_strings(value):
        for root in private_roots:
            if _contains_path_component(text, root):
                hits.append({"location": location, "root": str(root), "value": text})
    if hits:
        raise ContractError(f"{label} contains private stage/NVMe paths: {hits[:3]}")


def _within(path_value: str, root: Path) -> bool:
    """Use path-component containment instead of string prefix matching."""

    try:
        Path(path_value).resolve(strict=False).relative_to(root.resolve(strict=False))
    except (ValueError, OSError):
        return False
    return True


def _require_final_output_path(value: Any, final_output: Path, label: str) -> None:
    if not isinstance(value, str) or not Path(value).is_absolute() or not _within(value, final_output):
        raise ContractError(f"{label} must be contained by the final Home output: {value!r}")


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _input_closure(request: Mapping[str, Any]) -> dict[str, str]:
    """Validate a root-enabled metadata closure without opening payload files."""

    files = request.get("input_files")
    hashes = request.get("input_sha256")
    if not isinstance(files, list) or not isinstance(hashes, dict) or not files:
        raise ContractError("enabled execution requires input_files/input_sha256")
    if set(files) != set(hashes):
        raise ContractError("enabled input_files/input_sha256 key sets differ")
    result: dict[str, str] = {}
    for value in files:
        path = _absolute(value, "input file")
        _reject_payload_path(path, "enabled input file")
        if path.name == "resource-ledger.json":
            raise ContractError("mutable resource ledger is read under its lock, not part of input closure")
        if path.suffix.lower() not in {".json", ".py", ".xmf", ".xml", ".txt", ".log", ""} or (path.suffix == "" and path.name not in {"pvpython", "python", "env"}):
            raise ContractError(f"enabled input closure contains an unsupported payload type: {path}")
        expected = _hex64(hashes[value], f"input_sha256[{value}]")
        if not path.is_file() or _sha256(path) != expected:
            raise ContractError(f"enabled metadata input digest mismatch: {path}")
        result[str(path)] = expected
    return result


def _ledger_file(lock_path: Path) -> Path:
    ledger = lock_path.parent / "resource-ledger.json"
    if not ledger.is_file():
        raise ContractError(f"runtime resource-ledger.json is missing beside lock: {ledger}")
    return ledger


def _live_resource_snapshot(lock_path: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    """Read the live ledger while its lock is held; never mutate that ledger."""

    ledger_path = _ledger_file(lock_path)
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read live resource ledger: {ledger_path}") from exc
    if not isinstance(ledger, dict) or ledger.get("schema") != "ds02.resource-ledger.v1":
        raise ContractError("unexpected live resource-ledger schema")
    limits = ledger.get("limits")
    reservations = ledger.get("reservations")
    if not isinstance(limits, dict) or not isinstance(reservations, list):
        raise ContractError("live resource ledger lacks limits/reservations")
    home_root = _absolute(request["home_root"], "home_root").resolve()
    if limits.get("storage_policy") != "home_free_floor" or Path(str(limits.get("home_path", ""))).resolve() != home_root:
        raise ContractError("live ledger does not authorize the requested Home-floor root")
    live_floor = int(limits.get("home_min_free_bytes", 0))
    if live_floor < DEFAULT_HOME_FLOOR:
        raise ContractError("live ledger Home floor is below the approved 500 GiB")
    reservation_id = request.get("reservation_id")
    if not isinstance(reservation_id, str) or not reservation_id:
        raise ContractError("enabled execution requires reservation_id")
    if request.get("current_attempt_id") != reservation_id:
        raise ContractError("current_attempt_id must equal the active reservation id")
    owned = [row for row in reservations if isinstance(row, dict) and row.get("id") == reservation_id]
    if len(owned) != 1:
        raise ContractError("active reservation id is not uniquely present in the live ledger")
    own = owned[0]
    if int(own.get("cpu_threads", -1)) != int(request["cpu_threads"]):
        raise ContractError("active reservation CPU threads differ from request")
    if int(own.get("cpu_core_seconds", -1)) < int(request["cpu_threads"]) * int(request["max_wall_seconds"]):
        raise ContractError("active reservation CPU budget is smaller than the renderer wall reservation")
    others = [row for row in reservations if row is not own]
    active_cpu24 = sum(int(row.get("cpu_threads", 0)) == DEFAULT_CPU_THREADS for row in others if isinstance(row, dict))
    if active_cpu24 + 1 > int(request["global_renderer_cap"]):
        raise ContractError("live renderer cap would be exceeded")
    reserved_threads = sum(int(row.get("cpu_threads", 0)) for row in others if isinstance(row, dict))
    if reserved_threads + int(request["cpu_threads"]) > 64:
        raise ContractError("live CPU reservation cap would be exceeded")
    reserved_bytes = sum(int(row.get("new_storage_bytes", 0)) for row in others if isinstance(row, dict))
    return {
        "ledger_path": str(ledger_path),
        "live_home_floor_bytes": live_floor,
        "live_reserved_bytes_excluding_own": reserved_bytes,
        "live_cpu_threads_excluding_own": reserved_threads,
        "live_renderer24_count_excluding_own": active_cpu24,
        "own_reservation_id": reservation_id,
    }


def _required(request: Mapping[str, Any], keys: Sequence[str]) -> None:
    missing = [key for key in keys if key not in request]
    if missing:
        raise ContractError("missing request fields: " + ", ".join(missing))


def validate_request(request: Mapping[str, Any], *, execution: bool = False) -> dict[str, Any]:
    """Validate a successor request without opening scientific payloads."""

    _required(request, (
        "schema", "family_id", "case_id", "attempt_id", "manifest", "renderer",
        "pvpython", "home_root", "home_output", "nvme_root", "worktree_root",
        "cwd", "launch_owner", "cpu_threads", "declared_cpu_cores",
        "environment_threads", "max_wall_seconds", "global_renderer_cap",
        "home_free_floor_bytes", "home_reserved_bytes", "nvme_free_floor_bytes",
        "nvme_stage_cap_bytes", "home_publish_cap_bytes", "expected_frames",
        "expected_particles", "expected_contact_sheets", "keyframe_indices",
        "disabled", "launch", "launch_allowed", "execution_allowed",
        "source_only", "future_input_hashes_null", "output_child",
        "render_environment", "resource_ledger_lock", "reservation_id",
        "current_attempt_id", "renderer_argv_template",
    ))
    if request["schema"] != SCHEMA:
        raise ContractError(f"unsupported request schema: {request['schema']!r}")
    if not isinstance(request["family_id"], str) or not request["family_id"]:
        raise ContractError("family_id must be a non-empty family identifier")
    for key in ("manifest", "renderer", "pvpython", "home_root", "home_output", "nvme_root", "worktree_root", "cwd", "resource_ledger_lock"):
        _absolute(request[key], key)
    manifest = _absolute(request["manifest"], "manifest")
    renderer = _absolute(request["renderer"], "renderer")
    _reject_payload_path(manifest, "manifest")
    _reject_payload_path(renderer, "renderer")
    if manifest.suffix.lower() != ".json" or renderer.suffix.lower() != ".py":
        raise ContractError("manifest must be JSON and renderer must be Python")
    if not isinstance(request["attempt_id"], str) or not request["attempt_id"]:
        raise ContractError("attempt_id must be non-empty")
    if request["output_child"] != "render":
        raise ContractError("Root023 output child must be exactly 'render'")
    if request["launch_owner"] != "root":
        raise ContractError("only Root may own execution")
    if request["current_attempt_id"] is not None and not isinstance(request["current_attempt_id"], str):
        raise ContractError("current_attempt_id must be null or a reservation id")
    if int(request["cpu_threads"]) != DEFAULT_CPU_THREADS or int(request["declared_cpu_cores"]) != DEFAULT_CPU_THREADS:
        raise ContractError("renderer must reserve CPU24")
    if int(request["environment_threads"]) != DEFAULT_ENV_THREADS:
        raise ContractError("renderer environment must use env2")
    if int(request["global_renderer_cap"]) != DEFAULT_RENDER_CAP:
        raise ContractError("global renderer cap must remain 2")
    if int(request["home_free_floor_bytes"]) < DEFAULT_HOME_FLOOR:
        raise ContractError("Home free floor is below 500 GiB")
    if int(request["nvme_free_floor_bytes"]) < DEFAULT_NVME_FLOOR:
        raise ContractError("NVMe free floor is below 100 GiB")
    if int(request["nvme_stage_cap_bytes"]) > DEFAULT_STAGE_CAP:
        raise ContractError("NVMe stage cap may not exceed 24 GiB")
    if int(request["home_publish_cap_bytes"]) > DEFAULT_HOME_CAP:
        raise ContractError("Home publish cap may not exceed 3 GiB")
    if int(request["max_wall_seconds"]) != 14400:
        raise ContractError("renderer wall limit must remain 14400 seconds")
    if int(request["expected_frames"]) <= 0 or int(request["expected_particles"]) <= 0:
        raise ContractError("expected frames and particles must be positive")
    contacts = int(request["expected_contact_sheets"])
    if contacts <= 0:
        raise ContractError("expected contact sheets must be positive")
    keys = request["keyframe_indices"]
    if not isinstance(keys, list) or not keys or any(int(frame) < 0 or int(frame) >= int(request["expected_frames"]) for frame in keys):
        raise ContractError("keyframe_indices must be in the saved frame range")
    environment = request["render_environment"]
    if not isinstance(environment, dict):
        raise ContractError("render_environment must be an object")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "LP_NUM_THREADS", "VTK_SMP_MAX_THREADS"):
        if str(environment.get(name)) != "2":
            raise ContractError(f"render environment missing env2 setting: {name}")
    expected_environment = {
        "LIBGL_ALWAYS_SOFTWARE": "1",
        "MESA_GLTHREAD": "false",
        "MESA_LOADER_DRIVER_OVERRIDE": "llvmpipe",
        "QT_QPA_PLATFORM": "offscreen",
        "VTK_DEFAULT_OPENGL_WINDOW": "vtkEGLRenderWindow",
        "__EGL_VENDOR_LIBRARY_FILENAMES": "/usr/share/glvnd/egl_vendor.d/50_mesa.json",
    }
    for name, expected in expected_environment.items():
        if str(environment.get(name)) != expected:
            raise ContractError(f"Root732 software/offscreen environment is incomplete: {name}")
    argv_template = request["renderer_argv_template"]
    expected_argv_template = [
        str(_absolute(request["pvpython"], "pvpython")),
        "--force-offscreen-rendering",
        str(renderer),
        "--manifest",
        "{manifest}",
        "--output-dir",
        "{stage_render}",
    ]
    if argv_template != expected_argv_template:
        raise ContractError("Root732 full-render argv contract differs")
    if execution:
        if request["disabled"] is True or request["launch"] is not True or request["launch_allowed"] is not True or request["execution_allowed"] is not True:
            raise ContractError("disabled request cannot execute")
        if request["source_only"] is not False or request["future_input_hashes_null"] is not False:
            raise ContractError("enabled execution must be an adopted binding, not the disabled source request")
        closure = _input_closure(request)
        if str(manifest) not in closure or str(renderer) not in closure:
            raise ContractError("enabled input closure must bind the manifest and renderer source")
        if not manifest.exists() or not renderer.exists() or not _absolute(request["pvpython"], "pvpython").exists():
            raise ContractError("execution inputs are not present")
        if not isinstance(request["reservation_id"], str) or not request["reservation_id"]:
            raise ContractError("active runtime reservation is required")
        if request["current_attempt_id"] != request["reservation_id"]:
            raise ContractError("current_attempt_id must correspond to reservation.id")
        lock = _absolute(request["resource_ledger_lock"], "resource_ledger_lock")
        if not lock.exists():
            raise ContractError("runtime resource-ledger.lock is missing")
    else:
        if request["disabled"] is not True or request["launch"] is not False or request["launch_allowed"] is not False or request["execution_allowed"] is not False or request["source_only"] is not True or request["future_input_hashes_null"] is not True:
            raise ContractError("source handoff must remain disabled")
    home_output = _absolute(request["home_output"], "home_output")
    home_root = _absolute(request["home_root"], "home_root")
    _resolve_under(home_output, home_root / "Projects/DualSPHysics-data/ds-data-02", "home_output")
    if home_output.exists() and execution:
        raise ContractError(f"refusing to overwrite an existing product: {home_output}")
    return {"manifest": str(manifest), "renderer": str(renderer), "home_output": str(home_output), "home_root": str(home_root)}


def _manifest_metadata(request: Mapping[str, Any]) -> dict[str, Any]:
    """Read only the JSON/XMF metadata needed before ParaView starts."""

    manifest = _load_json(_absolute(request["manifest"], "manifest"), "XDMF manifest")
    if manifest.get("schema") != "ds02.stage1.paraview-temporal-product.v1":
        raise ContractError("unexpected Root023 manifest schema")
    if int(manifest.get("frames", -1)) != int(request["expected_frames"]):
        raise ContractError("manifest frame count differs from request")
    if int(manifest.get("particles", -1)) != int(request["expected_particles"]):
        raise ContractError("manifest particle count differs from request")
    xdmf = _absolute(manifest.get("xdmf"), "manifest.xdmf")
    if xdmf.suffix.lower() != ".xmf" or not xdmf.exists():
        raise ContractError("manifest XDMF path is missing or not an XMF")
    # The XMF is delegated to Root023.  This preflight intentionally does not
    # parse it and never follows its H5 DataItem references.
    return {
        "schema": manifest["schema"],
        "manifest": str(manifest),
        "frames": int(manifest["frames"]),
        "particles": int(manifest["particles"]),
        "xdmf": str(xdmf),
    }


def preflight_request(request: Mapping[str, Any]) -> dict[str, Any]:
    fields = validate_request(request, execution=False)
    metadata = _manifest_metadata(request)
    return {"valid": True, "disabled": True, "source_only": True, "science_payloads_opened": False, **fields, "manifest_metadata": metadata}


def _validate_report(stage_render: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    report_path = stage_render / "paraview-full-animation-report.json"
    report = _load_json(report_path, "Root023 report")
    if report.get("schema") != REPORT_SCHEMA:
        raise ContractError("Root023 report schema mismatch")
    if int(report.get("frames", -1)) != int(request["expected_frames"]) or int(report.get("source_frames", -1)) != int(request["expected_frames"]):
        raise ContractError("Root023 did not produce all expected frames")
    if report.get("all_frames_rendered") is not True or report.get("actual_times_preserved_exactly") is not True:
        raise ContractError("Root023 report does not prove a full saved-time render")
    frames_dir = stage_render / "frames"
    frame_files = sorted(frames_dir.glob("frame_*.png")) if frames_dir.exists() else []
    contact_files = sorted(stage_render.glob("all_frames_*.png"))
    if len(frame_files) != int(request["expected_frames"]):
        raise ContractError("saved frame PNG count differs from expected frames")
    if len(contact_files) != int(request["expected_contact_sheets"]):
        raise ContractError("contact sheet count differs from request")
    outputs = report.get("outputs")
    if not isinstance(outputs, dict):
        raise ContractError("Root023 report outputs object is missing")
    for key in ("gif", "pvsm"):
        value = outputs.get(key)
        if not isinstance(value, str) or Path(value) != stage_render / Path(value).name or not Path(value).exists():
            raise ContractError(f"Root023 {key} output is not inside staging output")
    key_paths = []
    for frame in request["keyframe_indices"]:
        path = frames_dir / f"frame_{int(frame):04d}.png"
        if not path.exists():
            raise ContractError(f"required keyframe is missing: {path}")
        key_paths.append(str(path))
    return {"report_path": str(report_path), "report": report, "frame_files": [str(p) for p in frame_files], "contact_files": [str(p) for p in contact_files], "keyframe_files": key_paths}


def _rewrite_report(
    stage_render: Path,
    final_output: Path,
    *,
    private_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    report_path = stage_render / "paraview-full-animation-report.json"
    report = _load_json(report_path, "Root023 report")
    report = _replace_prefix(report, str(stage_render), str(final_output))
    _reject_private_paths(report, tuple(private_roots or (stage_render,)), "rewritten Root023 report")
    _write_json(report_path, report)
    return report


def _rewrite_pvsm(
    stage_render: Path,
    final_output: Path,
    *,
    private_roots: Sequence[Path] | None = None,
) -> bool:
    """Rebind stage paths and reject every remaining private path in PVSM text."""

    pvsm = stage_render / "case.pvsm"
    if not pvsm.exists():
        raise ContractError("Root023 state file is missing")
    try:
        text = pvsm.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ContractError("Root023 state file is not readable text") from exc
    changed = str(stage_render) in text
    if changed:
        text = text.replace(str(stage_render), str(final_output))
        pvsm.write_text(text, encoding="utf-8")
    _reject_private_paths(text, tuple(private_roots or (stage_render,)), "rewritten ParaView state")
    return changed


def _report_paths_rebound(
    stage_render: Path,
    final_output: Path,
    *,
    private_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Return the stable on-disk report after path rebinding."""

    report_path = stage_render / "paraview-full-animation-report.json"
    report = _load_json(report_path, "rewritten Root023 report")
    _reject_private_paths(report, tuple(private_roots or (stage_render,)), "rewritten Root023 report")
    outputs = report.get("outputs")
    if not isinstance(outputs, dict):
        raise ContractError("rewritten report outputs object is missing")
    for key in ("frames_dir", "gif", "pvsm"):
        value = outputs.get(key)
        _require_final_output_path(value, final_output, f"rewritten report output {key}")
    return report


def _publish_files(
    stage_render: Path,
    final_output: Path,
    request: Mapping[str, Any],
    report: Mapping[str, Any],
    *,
    private_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    lock_path = _absolute(request["resource_ledger_lock"], "resource_ledger_lock")
    if not lock_path.exists():
        raise ContractError("runtime resource-ledger.lock is missing")
    roots = tuple(private_roots or (stage_render, _absolute(request["nvme_root"], "nvme_root")))
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        live = _live_resource_snapshot(lock_path, request)
        report = _report_paths_rebound(stage_render, final_output, private_roots=roots)
        files = _walk_files(stage_render)
        rows = [{"relative_path": str(path.relative_to(stage_render)), "bytes": path.stat().st_size, "sha256": _sha256(path)} for path in files]
        publish_bytes = sum(int(row["bytes"]) for row in rows)
        if publish_bytes > int(request["home_publish_cap_bytes"]):
            raise ContractError(f"Home publish cap exceeded before any Home write: {publish_bytes} bytes")
        home_root = _absolute(request["home_root"], "home_root")
        usage = shutil.disk_usage(home_root)
        reserved = int(live["live_reserved_bytes_excluding_own"])
        floor = int(live["live_home_floor_bytes"])
        if usage.free - reserved - publish_bytes < floor:
            raise ContractError("Home free-floor check failed before publication")
        parent = final_output.parent
        if not parent.exists() or not parent.is_dir():
            raise ContractError(f"final product parent must already exist: {parent}")
        if final_output.exists():
            raise ContractError(f"refusing to overwrite existing final product: {final_output}")
        receipt = {
            "schema": "ds02.stage1.f3.fresh112.render-publish-receipt.v1",
            "status": "published_after_atomic_rename",
            "case_id": request["case_id"],
            "attempt_id": request["attempt_id"],
            "reservation_id": request["reservation_id"],
            "published_output_root": str(final_output),
            "source_h5_opened_or_hashed_by_wrapper": False,
            "renderer_delegated_to_root023": True,
            "home_publish_cap_bytes": int(request["home_publish_cap_bytes"]),
            "published_bytes_excluding_receipt": publish_bytes,
            "files_excluding_receipt": rows,
            "report_output_paths_rewritten_to_final_home": True,
            "report_sha256_after_rebind": _sha256(stage_render / "paraview-full-animation-report.json"),
            "pvsm_private_stage_paths_rebound": True,
            "resource_ledger_path": str(_ledger_file(lock_path)),
            "live_home_floor_bytes": floor,
            "live_reserved_bytes_excluding_own": reserved,
            "live_renderer24_count_excluding_own": int(live["live_renderer24_count_excluding_own"]),
            "own_reservation_id": live["own_reservation_id"],
            "published_bytes_total": 0,
            "publish_fixed_point_iterations": 0,
        }
        receipt_path = stage_render / "render-publish-receipt.json"
        rows_all: list[dict[str, Any]] = []
        total = 0
        fixed_point_iterations = 0
        for _ in range(4):
            fixed_point_iterations += 1
            receipt["publish_fixed_point_iterations"] = fixed_point_iterations
            _write_json(receipt_path, receipt)
            files = _walk_files(stage_render)
            rows_all = [{"relative_path": str(path.relative_to(stage_render)), "bytes": path.stat().st_size, "sha256": _sha256(path)} for path in files]
            total = sum(int(row["bytes"]) for row in rows_all)
            if total > int(request["home_publish_cap_bytes"]):
                raise ContractError(f"Home publish cap exceeded after receipt creation: {total} bytes")
            if int(receipt["published_bytes_total"]) == total:
                break
            receipt["published_bytes_total"] = total
        else:
            raise ContractError("render publish receipt did not reach a stable byte-size fixed point")
        receipt["publish_fixed_point_iterations"] = fixed_point_iterations
        _write_json(receipt_path, receipt)
        # The fixed-point iteration count is itself serialized in the receipt;
        # verify the final bytes and cap once more before any Home write.
        files = _walk_files(stage_render)
        rows_all = [{"relative_path": str(path.relative_to(stage_render)), "bytes": path.stat().st_size, "sha256": _sha256(path)} for path in files]
        total = sum(int(row["bytes"]) for row in rows_all)
        if total != int(receipt["published_bytes_total"]):
            raise ContractError("render publish receipt byte total changed after final serialization")
        if total > int(request["home_publish_cap_bytes"]):
            raise ContractError(f"Home publish cap exceeded after final receipt serialization: {total} bytes")
        stage_bytes = _tree_bytes(stage_render)
        if stage_bytes > int(request["nvme_stage_cap_bytes"]):
            raise ContractError(f"NVMe stage cap exceeded before Home publication: {stage_bytes} bytes")
        if shutil.disk_usage(home_root).free - reserved - total < floor:
            raise ContractError("Home free-floor check failed after final report/receipt serialization")
        # All report rewrites and byte-size checks are complete while the
        # runtime ledger lock is held.  Only the final rename publishes Home.
        temp = parent / f".{final_output.name}.publish-{uuid.uuid4().hex}"
        published = False
        post_publish_free: int | None = None
        try:
            temp.mkdir()
            for row in rows_all:
                src = stage_render / row["relative_path"]
                dst = temp / row["relative_path"]
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                if dst.stat().st_size != int(row["bytes"]) or _sha256(dst) != row["sha256"]:
                    raise ContractError(f"derived byte verification failed: {dst}")
            os.replace(temp, final_output)
            published = True
            post_publish_free = int(shutil.disk_usage(home_root).free)
            if post_publish_free - reserved < floor:
                # The product was created by this transaction and is still
                # under the ledger lock, so rollback is bounded and own-only.
                shutil.rmtree(final_output)
                published = False
                raise ContractError("Home free-floor check failed after atomic publication")
        except BaseException:
            if temp.exists():
                shutil.rmtree(temp)
            if published and final_output.exists():
                shutil.rmtree(final_output)
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    return {
        "status": "completed",
        "published_output_root": str(final_output),
        "published_bytes": total,
        "files": rows_all,
        "report": report,
        "post_publish_home_free_bytes": post_publish_free,
        "post_publish_home_floor_rechecked": True,
        "publish_fixed_point_iterations": fixed_point_iterations,
    }


def _terminate_owned_process(process: subprocess.Popen[Any], *, timeout: float = 30.0) -> None:
    """Terminate only the renderer process group created by this wrapper."""

    if process.poll() is not None:
        return
    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        return
    if pgid != process.pid:
        raise ContractError("renderer is not in its own process group; refusing broad signal")
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait()


def _remove_stage(stage_root: Path) -> None:
    """Remove private render bytes after publication or a rejected attempt."""

    if stage_root.exists():
        shutil.rmtree(stage_root)


def _write_rejection(nvme_root: Path, stage_root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    evidence = dict(payload)
    evidence.setdefault("schema", "ds02.stage1.f3.fresh112.render-rejection.v1")
    evidence["stage_root"] = str(stage_root)
    evidence["stage_removed_after_rejection"] = True
    path = nvme_root / f"{stage_root.name}.rejection.json"
    _write_json(path, evidence)
    _remove_stage(stage_root)
    return evidence


def execute_request(request: Mapping[str, Any], *, authorized: bool = False, popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen) -> dict[str, Any]:
    """Execute one root-enabled request with cleanup covering publication."""

    if not authorized:
        raise ContractError("Root execution authorization is required")
    validate_request(request, execution=True)
    metadata = _manifest_metadata(request)
    nvme_root = _absolute(request["nvme_root"], "nvme_root")
    nvme_root.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(nvme_root).free < int(request["nvme_free_floor_bytes"]):
        raise ContractError("NVMe free-floor check failed before staging")
    home_output = _absolute(request["home_output"], "home_output")
    stage_root = Path(tempfile.mkdtemp(prefix=f"{request['attempt_id']}-", dir=nvme_root))
    stage_render = stage_root / "render"
    stage_render.mkdir()
    stdout_path = stage_root / "renderer.stdout.log"
    stderr_path = stage_root / "renderer.stderr.log"
    renderer = _absolute(request["renderer"], "renderer")
    pvpython = _absolute(request["pvpython"], "pvpython")
    argv = [str(pvpython), "--force-offscreen-rendering", str(renderer), "--manifest", str(metadata["manifest"]), "--output-dir", str(stage_render)]
    environment = os.environ.copy()
    environment.update({str(k): str(v) for k, v in request["render_environment"].items()})
    started = time.monotonic()
    process: subprocess.Popen[Any] | None = None
    violation: str | None = None
    previous_handlers: dict[int, Any] = {}
    publication_complete = False

    def _signal_handler(signum: int, _frame: Any) -> None:
        if process is not None:
            _terminate_owned_process(process)
        raise ContractError(f"wrapper received signal {signum}; own renderer/publication cleanup is required")

    try:
        # SIGTERM otherwise exits the wrapper without running cleanup.  The
        # handlers only ever signal the process group created by this request.
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_handlers[signum] = signal.getsignal(signum)
            signal.signal(signum, _signal_handler)
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = popen(argv, cwd=str(_absolute(request["cwd"], "cwd")), env=environment, stdout=stdout, stderr=stderr, start_new_session=True)
            while process.poll() is None:
                if time.monotonic() - started > int(request["max_wall_seconds"]):
                    violation = "renderer wall limit exceeded"
                try:
                    stage_size = _tree_bytes(stage_root)
                    free = shutil.disk_usage(nvme_root).free
                    if stage_size > int(request["nvme_stage_cap_bytes"]):
                        violation = f"NVMe stage cap exceeded: {stage_size}"
                    elif free < int(request["nvme_free_floor_bytes"]):
                        violation = f"NVMe free floor violated: {free}"
                except (OSError, ContractError) as exc:
                    violation = str(exc)
                if violation:
                    _terminate_owned_process(process)
                    break
                time.sleep(1.0)
            returncode = process.wait()
        if violation:
            return _write_rejection(nvme_root, stage_root, {
                "status": "rejected_before_publish",
                "reason": violation,
                "home_output_absent": not home_output.exists(),
                "source_h5_opened_or_hashed_by_wrapper": False,
            })
        if returncode != 0:
            return _write_rejection(nvme_root, stage_root, {
                "status": "renderer_failed",
                "returncode": returncode,
                "home_output_absent": not home_output.exists(),
                "source_h5_opened_or_hashed_by_wrapper": False,
            })
        try:
            private_roots = (stage_root, nvme_root)
            _validate_report(stage_render, request)
            report = _rewrite_report(stage_render, home_output, private_roots=private_roots)
            _rewrite_pvsm(stage_render, home_output, private_roots=private_roots)
            result = _publish_files(stage_render, home_output, request, report, private_roots=private_roots)
            publication_complete = True
        except ContractError as exc:
            return _write_rejection(nvme_root, stage_root, {
                "status": "rejected_before_publish",
                "reason": str(exc),
                "home_output_absent": not home_output.exists(),
                "source_h5_opened_or_hashed_by_wrapper": False,
            })
        _remove_stage(stage_root)
        return result
    except BaseException as exc:
        if process is not None and process.poll() is None:
            _terminate_owned_process(process)
        if publication_complete:
            if stage_root.exists():
                _remove_stage(stage_root)
            raise
        if stage_root.exists():
            return _write_rejection(nvme_root, stage_root, {
                "status": "wrapper_exception_before_publish",
                "reason": repr(exc),
                "home_output_absent": not home_output.exists(),
                "source_h5_opened_or_hashed_by_wrapper": False,
            })
        raise
    finally:
        # Keep the handlers installed through report rewrite, fixed-point byte
        # accounting, atomic rename, and own-stage cleanup.
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path)
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--execute", action="store_true", help="root-only future action; never used by source tests")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    request = _load_json(args.request, "successor request")
    if args.execute:
        result = execute_request(request, authorized=True)
    else:
        result = preflight_request(request)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
