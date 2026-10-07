#!/usr/bin/env python3
"""Guard-ready F2-S1 portable replay orchestration.

The worker has one explicit sequence: build a source profile, copy the full
role bundle, prepare the relocated request, run the copied v15 metadata
preflight, and (only with ``--io-slot-approved``) read the complete 401-frame
typed HDF5 trajectory.  Without that flag it performs profile construction and
reports the parent I/O gate as pending; it never opens an HDF5 dataset.

This worker is an orchestration product, not a raw-native converter.  The
native PartOut/RunPARTs anchors are copied and source-bound as evidence, while
the v15 consumer reads the producer's typed HDF5.  No raw-to-typed or
raw-to-label reconstruction is invoked, so every result remains DEVELOPMENT
and QI/QN/QE are UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Sequence

import ds_data02_stage2_f2_portable_v19 as portable


REQUEST_SCHEMA = "ds02.request.v1"
ORCHESTRATION_SCHEMA = "ds02.stage2.f2-s1-portable-orchestration.v19"


class OrchestrationV19Error(ValueError):
    """Raised when an orchestration request cannot be executed safely."""


def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise OrchestrationV19Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise OrchestrationV19Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists():
        raise OrchestrationV19Error(f"refusing to overwrite existing destination: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
    except FileExistsError as error:
        raise OrchestrationV19Error(f"refusing to overwrite existing destination: {target}") from error


def _require_request(request: Mapping[str, Any]) -> None:
    if request.get("schema") != REQUEST_SCHEMA:
        raise OrchestrationV19Error("shared ds02.request.v1 schema is required")
    if request.get("orchestration_schema") != ORCHESTRATION_SCHEMA:
        raise OrchestrationV19Error("v19 orchestration schema is required")
    if request.get("model_invoked") is not False:
        raise OrchestrationV19Error("model invocation is forbidden")
    if request.get("qualification") != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
        raise OrchestrationV19Error("orchestration qualification must remain UNKNOWN")


def _source_ref(request: Mapping[str, Any], key: str) -> tuple[Path, str]:
    refs = request.get("source_bindings")
    if not isinstance(refs, Mapping) or not isinstance(refs.get(key), Mapping):
        raise OrchestrationV19Error(f"source_bindings.{key} is required")
    item = refs[key]
    path = item.get("path")
    expected = item.get("sha256")
    if not isinstance(path, str) or not isinstance(expected, str):
        raise OrchestrationV19Error(f"source_bindings.{key} path/sha256 is malformed")
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise OrchestrationV19Error(f"source binding is missing: {source}")
    actual = sha256(source)
    if actual != expected:
        raise OrchestrationV19Error(f"source binding SHA differs: {key}")
    return source, expected


def _installed_dependency_manifest() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for module_name, distribution in (("numpy", "numpy"), ("h5py", "h5py")):
        try:
            module = __import__(module_name)
            module_path = Path(str(module.__file__)).resolve()
            version = importlib.metadata.version(distribution)
            digest = sha256(module_path) if module_path.is_file() else None
        except (ImportError, OSError, importlib.metadata.PackageNotFoundError) as error:
            entries.append({"module": module_name, "distribution": distribution,
                            "status": "MISSING_OR_UNREADABLE", "error": str(error)})
            continue
        entries.append({"module": module_name, "distribution": distribution,
                        "version": version, "module_file": str(module_path),
                        "module_file_sha256": digest, "scope": "installed_dependency"})
    return entries


def _execution_closure() -> dict[str, Any]:
    script_dir = Path(__file__).resolve().parent
    local = []
    for name in (
        "ds_data02_stage2_f2_portable_orchestrator_v19.py",
        "ds_data02_stage2_f2_portable_v19.py",
        "ds_data02_stage2_f2_portable_v16.py",
        "ds_data02_stage2_f2_replay_runner_v19.py",
        "ds_data02_stage2_f2_replay_v15.py",
        "ds_data02_stage2_f2_replay_v14.py",
    ):
        path = script_dir / name
        local.append({"module": name, "path": str(path.resolve()),
                      "sha256": sha256(path) if path.is_file() else None})
    return {
        "local_modules": local,
        "imports": {
            "runner_v19": ["portable_v19 (dynamic copied import)", "replay_v15 (dynamic copied import)"],
            "portable_v19": ["portable_v16"],
            "replay_v15": ["replay_v14", "numpy"],
            "replay_v14": ["numpy", "h5py (approved HDF5 read path)", "Python stdlib"],
        },
        "historical_v11_v12": {
            "v11": "NOT_IMPORTED_BY_V19_V15_V14; retained only as historical development evidence",
            "v12": "NOT_IMPORTED_BY_V19_V15_V14; v12 request schema is rejected",
        },
        "installed_dependencies": _installed_dependency_manifest(),
        "python": {
            "executable": str(Path(sys.executable).resolve()),
            "version": sys.version,
            "executable_sha256": sha256(Path(sys.executable).resolve()),
        },
        "shared_four_guard_sources": {
            "runtime_v2": "main process binds ds_data02_runtime_v2.py",
            "runtime_v1": "immutable historical runtime source",
            "stage2_dispatch": "main process resource/parent dispatch",
            "strict_dispatch": "main process input digest guard",
        },
    }


def _run_runner(runner: Path, profile: Path, request: Path, path_map: Path,
                output: Path, *, io_slot_approved: bool) -> dict[str, Any]:
    command = [
        sys.executable, str(runner),
        "--profile", str(profile),
        "--request", str(request),
        "--path-map", str(path_map),
        "--output", str(output),
    ]
    if io_slot_approved:
        command.append("--io-slot-approved")
    completed = subprocess.run(command, cwd=str(Path(__file__).resolve().parents[1]),
                               text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "runner failed").strip()
        raise OrchestrationV19Error(f"v19 runner failed ({completed.returncode}): {detail[-4000:]}")
    return _load(output)


def run(request_path: Path | str, output_dir: Path | str, *,
        io_slot_approved: bool = False, metadata_only: bool = False) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load(request_file)
    _require_request(request)
    target = Path(output_dir).expanduser()
    if target.exists():
        raise OrchestrationV19Error(f"refusing to use existing orchestration output directory: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir()
    stages: list[dict[str, Any]] = []
    closure = _execution_closure()
    v15_request, v15_sha = _source_ref(request, "v15_replay_request")
    sidecar, sidecar_sha = _source_ref(request, "v16_flux_forward_sidecar")
    profile_path = target / "f2-s1-portable-source-profile-v19-001.json"
    try:
        profile = portable.build_profile(v15_request, sidecar, profile_path)
    except Exception:
        # build_profile itself never writes an output until validation succeeds;
        # preserve the empty/new directory for the parent receipt to inspect.
        raise
    stages.append({"stage": "build-profile", "status": "COMPLETE",
                   "output": str(profile_path), "profile_sha256": profile["sha256"],
                   "hdf5_dataset_read": False})

    report: dict[str, Any] = {
        "schema": ORCHESTRATION_SCHEMA,
        "status": "PROFILE_READY_PARENT_IO_SLOT_PENDING",
        "request_id": request.get("request_id"),
        "request_schema": request.get("schema"),
        "source_request": {"path": str(v15_request), "sha256": v15_sha},
        "sidecar": {"path": str(sidecar), "sha256": sidecar_sha},
        "stages": stages,
        "execution_closure": closure,
        "io_slot_approved": bool(io_slot_approved),
        "trajectory_read": False,
        "hdf5_dataset_read_by_profile": False,
        "model_invoked": False,
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "raw_to_typed_gap": {
            "raw_native_roles_bound_as_evidence": ["native_partout", "native_runparts",
                                                    "native_reconciliation", "native_reconciliation_receipt"],
            "typed_h5_consumer": "v15/v14 reads producer typed trajectory.h5",
            "raw_to_typed_reconstruction_invoked": False,
            "raw_to_label_complete": False,
            "missing_closure": [
                "native PartOut/RunPARTs to typed-array reconstruction receipt",
                "raw invalid/missing-state to label provenance adapter",
                "raw-to-label evaluator identity/order proof",
            ],
            "qualification": "UNKNOWN",
        },
    }
    if not io_slot_approved:
        report["status"] = "PROFILE_READY_PARENT_IO_SLOT_PENDING"
        report["stages"].append({"stage": "copy-bundle", "status": "PENDING_PARENT_IO_SLOT",
                                 "hdf5_copy": False})
        report["stages"].append({"stage": "prepare-replay", "status": "PENDING_PARENT_IO_SLOT"})
        report["stages"].append({"stage": "metadata-v15-preflight", "status": "PENDING_PARENT_IO_SLOT"})
        report["stages"].append({"stage": "full401-replay", "status": "PENDING_PARENT_IO_SLOT"})
        if metadata_only:
            report["scope"] = "metadata-only plan; no HDF5 path opened"
        return report

    bundle_root = target / "bundle-v19"
    copy_receipt = portable.copy_bundle(profile, bundle_root, copy_hdf5=True, io_slot_approved=True)
    copy_path = target / "copy-result-v19.json"
    _write_new(copy_path, copy_receipt)
    stages.append({"stage": "copy-bundle", "status": "COMPLETE",
                   "output": str(copy_path), "hdf5_content_hash_verified": True})
    path_map = copy_receipt["path_map"]
    overlay_path = target / "replay-input-v19.json"
    overlay = portable.prepare_replay(profile, path_map, v15_request, overlay_path,
                                      full_replay=True, profile_path=profile_path)
    stages.append({"stage": "prepare-replay", "status": "COMPLETE",
                   "output": str(overlay_path), "profile_sha256": overlay["profile_sha256"]})
    runner = Path(path_map["replay_runner_v19"]).resolve()
    copied_request = Path(path_map["v15_replay_request"]).resolve()
    preflight_path = target / "metadata-preflight-v19.json"
    preflight = _run_runner(runner, profile_path, copied_request, overlay_path, preflight_path,
                            io_slot_approved=False)
    _write_new(target / "metadata-preflight-summary-v19.json", {
        "schema": "ds02.stage2.f2-s1-v15-metadata-preflight.v19",
        "runner_report": str(preflight_path),
        "status": preflight.get("status"),
        "access_audit": preflight.get("access_audit"),
        "typed_replay_scope": preflight.get("typed_replay_scope"),
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    })
    stages.append({"stage": "metadata-v15-preflight", "status": preflight.get("status"),
                   "output": str(preflight_path), "trajectory_read": False})
    if metadata_only:
        report["status"] = "METADATA_PREFLIGHT_COMPLETE_FULL_REPLAY_PENDING"
        report["trajectory_read"] = False
        report["stages"].append({"stage": "full401-replay", "status": "SKIPPED_METADATA_ONLY"})
        return report

    full_path = target / "full401-replay-v19.json"
    full = _run_runner(runner, profile_path, copied_request, overlay_path, full_path,
                       io_slot_approved=True)
    stages.append({"stage": "full401-replay", "status": full.get("status", full.get("runner_status")),
                   "output": str(full_path), "trajectory_read": True,
                   "access_audit": full.get("access_audit")})
    report["status"] = "COMPLETE_PROVISIONAL_TYPED_REPLAY"
    report["trajectory_read"] = True
    report["full_replay_report"] = str(full_path)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--io-slot-approved", action="store_true")
    parser.add_argument("--metadata-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        result = run(args.request, args.output_dir,
                     io_slot_approved=args.io_slot_approved,
                     metadata_only=args.metadata_only)
        report_path = args.report or args.output_dir / "orchestration-report-v19.json"
        _write_new(report_path, result)
    except (OSError, OrchestrationV19Error, portable.PortableV19BindingError) as error:
        parser.error(str(error))
    print(json.dumps({"status": result["status"], "schema": result["schema"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
