#!/usr/bin/env python3
"""Run the guarded ROOT279 → compact → scalar → verifier chain.

This is a parent-after-reservation worker.  The guarded ROOT279 producer is
still the only process that reads native Part files.  This wrapper only
orchestrates it and then reads bounded JSON products.  It is source-prepared
by ``stage2_f1_s2_root279_native_scalar_parent_request_v1.py``; it never
prehashes or opens deferred native files before the parent reservation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-worker.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v1"
JSON_CAP = 10 * 1024 * 1024


class ParentFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _read(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file() or path.suffix.lower() != ".json":
        raise ParentFailure(f"{label} is not a regular JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ParentFailure(f"{label} exceeds metadata cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise ParentFailure(f"{label} changed while being read")
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ParentFailure(f"{label} is not an object")
    return value, {"path": str(path), "sha256": _sha(raw), "stat": after, "bytes": len(raw)}


def _record(path: Path, label: str) -> dict[str, Any]:
    value, record = _read(path, label)
    return record


def _source_record(path: Path, label: str) -> dict[str, Any]:
    """Record a small imported source file without parsing it as JSON."""
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ParentFailure(f"{label} is not a regular source file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ParentFailure(f"{label} exceeds metadata cap: {path}")
    raw = path.read_bytes(); after = _stat(path)
    if before != after:
        raise ParentFailure(f"{label} changed while being read")
    return {"path": str(path), "sha256": _sha(raw), "stat": after,
            "bytes": len(raw), "payload_read_by_worker": False,
            "scope": "bounded_source_metadata"}


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise ParentFailure(f"refusing overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _replace_attempt(value: Any, attempt_root: Path) -> Any:
    if isinstance(value, str):
        return value.replace("{attempt_root}", str(attempt_root))
    if isinstance(value, list):
        return [_replace_attempt(item, attempt_root) for item in value]
    if isinstance(value, dict):
        return {key: _replace_attempt(item, attempt_root) for key, item in value.items()}
    return value


def _load_module(path: Path, name: str) -> Any:
    """Load a source-bound helper without importing from the ambient cwd."""
    path = _abs(path)
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ParentFailure(f"cannot load source-bound helper: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prepare_legacy_guard_manifest(source_manifest: Path, attempt_root: Path,
                                   bridge_path: Path) -> tuple[Path, dict[str, Any]]:
    """Project ROOT310 v3 metadata to the consumed v2 guard after reservation.

    The v3 manifest is the source of truth and remains untouched.  The old
    guard accepts only v2 records and its child parser requires a registered
    SI coordinate shape.  For rotation-invariant component diagnostics we give
    that parser an explicit identity *technical basis*; this is not a
    producer-to-world assertion and is recorded as such in the projected
    manifest.  No native path is opened here.
    """
    source, source_record = _read(source_manifest, "ROOT279 source manifest")
    schema = source.get("schema")
    if schema == "ds02.stage2.f1.native-selected-observer-manifest.v2":
        return source_manifest, {"source": source_record, "projection": "NONE_V2_INPUT"}
    if schema != "ds02.stage2.f1.native-selected-observer-manifest.v3-root310":
        raise ParentFailure(f"ROOT279 source manifest schema is unsupported: {schema}")
    bridge = _load_module(bridge_path, "stage2_root279_runtime_bridge")
    try:
        bridge.validate_v3_manifest(source)
        projected = bridge.project_v3_to_v2(source)
    except Exception as exc:
        raise ParentFailure(f"ROOT310 v3 manifest projection failed before native read: {exc}") from exc

    axis = projected.get("axis_authority")
    if not isinstance(axis, dict):
        raise ParentFailure("ROOT310 source manifest lacks axis_authority")
    coordinate = axis.get("coordinate_contract")
    if not isinstance(coordinate, dict):
        raise ParentFailure("ROOT310 source manifest lacks coordinate_contract")
    # The consumed V1 parser validates the registered SI shape.  Identity is
    # used only as a producer-component parser basis; the scientific result
    # keeps producer_to_world_orientation UNKNOWN and grants no directional Q.
    technical = {
        "frame": "world_cartesian_right_handed",
        "axis_labels": ["x", "y", "z"],
        "position_unit": coordinate.get("position_unit"),
        "velocity_unit": coordinate.get("velocity_unit"),
        "mass_unit": coordinate.get("mass_unit"),
        "time_unit": coordinate.get("time_unit"),
        "rotation_to_world": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    }
    if any(technical[key] != expected for key, expected in {
        "position_unit": "m", "velocity_unit": "m/s", "mass_unit": "kg", "time_unit": "s"
    }.items()):
        raise ParentFailure("ROOT310 source coordinate units are not registered SI")
    projected["axis_authority"] = {
        **axis,
        "coordinate_contract": technical,
        "producer_axis_orientation_metadata": "UNKNOWN",
        "technical_parser_basis": "PRODUCER_COMPONENT_XYZ_IDENTITY_ONLY",
        "world_orientation_claim": "UNKNOWN",
        "status_reason": "legacy V1 parser basis only; no producer-to-world calibration or directional scientific credit",
    }
    projected["bridge_projection"] = {
        **dict(projected.get("bridge_projection") or {}),
        "runtime_component_basis_adapter": "IDENTITY_FOR_LEGACY_PARSER_ONLY",
        "producer_to_world_orientation": "UNKNOWN",
        "scientific_credit": 0,
    }
    projected_path = attempt_root / "guarded-inputs" / "root279-v3-component-basis-v2-manifest.json"
    _write_once(projected_path, projected)
    return projected_path, {
        "source": source_record,
        "projection": "ROOT310_V3_TO_V2_COMPONENT_BASIS",
        "projected_manifest": _record(projected_path, "projected ROOT279 guard manifest"),
        "bridge": _source_record(bridge_path, "ROOT279 v3-to-v2 bridge"),
        "world_orientation": "UNKNOWN",
        "technical_parser_basis": "PRODUCER_COMPONENT_XYZ_IDENTITY_ONLY",
    }


def _ref(path: Path, label: str) -> dict[str, Any]:
    return {**_record(path, label), "label": label}


def _run(command: list[str], *, cwd: Path, timeout: float, label: str) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True,
                                   timeout=timeout, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ParentFailure(f"{label} timed out") from exc
    if completed.returncode != 0:
        raise ParentFailure(f"{label} failed rc={completed.returncode}: {completed.stderr[-4096:]}")
    return completed.returncode, completed.stdout[-65536:], completed.stderr[-65536:]


def run(manifest_path: Path, attempt_root: Path) -> dict[str, Any]:
    template, template_record = _read(manifest_path, "ROOT279 scalar parent manifest")
    if template.get("schema") != MANIFEST_SCHEMA:
        raise ParentFailure("parent manifest schema mismatch")
    if template.get("status") not in {"READY_FOR_PARENT_ROOT279_NATIVE_SCALAR", "WAITING_PARENT_ROOT279_NATIVE_SCALAR"}:
        raise ParentFailure("parent manifest is not parent-ready")
    attempt_root = _abs(attempt_root)
    attempt_root.mkdir(parents=True, exist_ok=True)
    config = template.get("runtime")
    if not isinstance(config, dict):
        raise ParentFailure("parent manifest lacks runtime configuration")
    python = _abs(config.get("literal_python"))
    guard = _abs(config.get("guard_worker"))
    v1_worker = _abs(config.get("native_child_worker"))
    compact_worker = _abs(config.get("compact_worker"))
    scalar_worker = _abs(config.get("scalar_worker"))
    verifier = _abs(config.get("verifier"))
    root279_manifest = _abs(config.get("root279_manifest"))
    root279_bridge = _abs(config.get("root279_bridge"))
    cwd = _abs(config.get("cwd"))
    for path, label in ((python, "literal Python"), (guard, "ROOT279 guard"), (v1_worker, "native child worker"),
                        (compact_worker, "compact worker"), (scalar_worker, "scalar worker"), (verifier, "scalar verifier"),
                        (root279_manifest, "ROOT279 source manifest"), (root279_bridge, "ROOT279 v3-to-v2 bridge")):
        if not path.exists():
            raise ParentFailure(f"{label} is unavailable: {path}")
    observer_dir = attempt_root / "observer"
    observer_dir.mkdir(parents=True, exist_ok=True)
    guard_output = observer_dir / "root279-guard-result.json"
    guard_log = observer_dir / "root279-guard.log"
    projected_manifest, projection_record = _prepare_legacy_guard_manifest(root279_manifest, attempt_root, root279_bridge)
    guard_command = [str(python), str(guard), "--run", "--manifest", str(projected_manifest),
                     "--attempt-root", str(attempt_root), "--output", str(guard_output),
                     "--log-path", str(guard_log), "--v1-worker", str(v1_worker),
                     "--python", str(python), "--cwd", str(cwd),
                     "--max-scratch-bytes", str(config.get("max_scratch_bytes", 256 * 1024 * 1024)),
                     "--max-log-bytes", str(config.get("max_log_bytes", 1024 * 1024)),
                     "--timeout-seconds", str(config.get("guard_timeout_seconds", 1800))]
    _run(guard_command, cwd=cwd, timeout=float(config.get("guard_timeout_seconds", 1800)) + 30, label="ROOT279 guarded producer")
    guard_value, guard_record = _read(guard_output, "ROOT279 guard output")
    if not str(guard_value.get("status", "")).startswith("PASS"):
        raise ParentFailure("ROOT279 guarded producer did not PASS")
    child_output = observer_dir / ".v1-result.json"
    if not child_output.is_file():
        child_ref = guard_value.get("child_output")
        if isinstance(child_ref, dict) and isinstance(child_ref.get("path"), str):
            child_output = _abs(child_ref["path"])
    if not child_output.is_file():
        raise ParentFailure("ROOT279 guard did not produce the child observer JSON")
    child_value, child_record = _read(child_output, "ROOT279 child observer output")
    compact_manifest = _replace_attempt(template["compact_manifest"], attempt_root)
    compact_manifest_path = observer_dir / "compact-manifest.json"
    compact_manifest["guard_result"] = guard_record
    compact_manifest["child_report"] = child_record
    compact_manifest["status"] = "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT"
    _write_once(compact_manifest_path, compact_manifest)
    compact_output_dir = observer_dir / "compact"
    _run([str(python), str(compact_worker), "--run", "--manifest", str(compact_manifest_path),
          "--output-dir", str(compact_output_dir)], cwd=cwd,
         timeout=float(config.get("compact_timeout_seconds", 300)), label="ROOT279 compact producer")
    compact_value, compact_result_record = _read(compact_manifest_path, "ROOT279 compact manifest after worker")
    compact_outputs = compact_value.get("outputs")
    if not isinstance(compact_outputs, dict):
        raise ParentFailure("compact worker manifest lost output records")
    scalar_manifest = _replace_attempt(template["scalar_manifest"], attempt_root)
    scalar_manifest_path = observer_dir / "scalar-manifest.json"
    scalar_manifest["attempts"] = []
    for label, attempt_id in (("same_cfl", "root279-same-cfl"), ("half_cfl", "root279-half-cfl")):
        output_ref = compact_outputs.get(label)
        if not isinstance(output_ref, dict):
            raise ParentFailure(f"compact output record missing for {label}")
        scalar_manifest["attempts"].append({
            "label": label, "attempt_id": attempt_id, "rows_key": "observations",
            "source_identity_digest": scalar_manifest["source_identity"]["source_identity_digest"],
            "report": output_ref,
        })
    _write_once(scalar_manifest_path, scalar_manifest)
    scalar_output_path = observer_dir / "scalar-result.json"
    _run([str(python), str(scalar_worker), "--run", "--manifest", str(scalar_manifest_path),
          "--output", str(scalar_output_path)], cwd=cwd,
         timeout=float(config.get("scalar_timeout_seconds", 300)), label="ROOT279 scalar consumer")
    verification_output = observer_dir / "scalar-verification.json"
    _run([str(python), str(verifier), "--verify", "--compact-manifest", str(compact_manifest_path),
          "--scalar-manifest", str(scalar_manifest_path), "--scalar-output", str(scalar_output_path),
          "--verification-output", str(verification_output)], cwd=cwd,
         timeout=float(config.get("verify_timeout_seconds", 300)), label="ROOT279 independent scalar verifier")
    _, scalar_record = _read(scalar_output_path, "ROOT279 scalar result")
    _, verification_record = _read(verification_output, "ROOT279 scalar verification")
    result = {
        "schema": SCHEMA,
        "status": "COMPLETE_ROOT279_NATIVE_PRODUCER_COMPACT_SCALAR_VERIFIER_CHAIN_NO_SCIENTIFIC_Q",
        "guard_result": guard_record, "child_report": child_record,
        "root279_projection": projection_record,
        "compact_manifest": _record(compact_manifest_path, "compact manifest"),
        "scalar_manifest": _record(scalar_manifest_path, "scalar manifest"),
        "scalar_result": scalar_record, "verification": verification_record,
        "read_scope": {"native_reader": "ROOT279 guarded producer only", "compact_json_consumer": True,
                        "native_payload_read_by_wrapper": False, "solver_launch": False, "gencase_launch": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
    }
    result_path = observer_dir / "root279-native-scalar-parent-result.json"
    _write_once(result_path, result)
    return result


def _self_test() -> None:
    # The full production guard is not started here.  The actual compact
    # worker/scalar/verifier chain is exercised by their own genuine tiny
    # fixtures; this entrypoint only validates the parent manifest boundary.
    with tempfile.TemporaryDirectory(prefix="root279-parent-worker-") as value:
        root = Path(value)
        manifest = {"schema": MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROOT279_NATIVE_SCALAR",
                    "runtime": {"literal_python": "/does/not/launch", "guard_worker": "/does/not/launch",
                                "native_child_worker": "/does/not/launch", "compact_worker": "/does/not/launch",
                                "scalar_worker": "/does/not/launch", "verifier": "/does/not/launch",
                                "root279_manifest": "/does/not/launch", "root279_bridge": "/does/not/launch",
                                "cwd": str(root)},
                    "compact_manifest": {"status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT"},
                    "scalar_manifest": {"schema": "ds02.stage2.rotation-invariant-native-scalar-manifest.v2"}}
        path = root / "manifest.json"; path.write_text(json.dumps(manifest) + "\n")
        loaded, _ = _read(path, "fixture manifest")
        assert loaded["schema"] == MANIFEST_SCHEMA
        assert loaded["runtime"]["cwd"] == str(root)
    print("PASS_ROOT279_NATIVE_SCALAR_PARENT_BOUNDARY_FIXTURE_NO_PRODUCTION_LAUNCH")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--attempt-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None or args.attempt_root is None:
            parser.error("--run requires --manifest and --attempt-root")
        result = run(args.manifest, args.attempt_root)
        print(json.dumps({"status": result["status"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (ParentFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_SCALAR_PARENT_WORKER: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
