#!/usr/bin/env python3
"""ROOT279 guarded producer -> compact V2 -> scalar -> verifier parent.

The consumed parent re-read the compact manifest after the compact worker,
where the output entries still contained only paths.  V2 consumes the
compact worker's sealed ``compact_reports`` records instead and writes a new
sealed manifest for the independent verifier.  It also keeps the producer
child status distinct from the wrapper status.  Native files are opened only
by the existing guarded producer after parent reservation.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
LEGACY_PATH = HERE / "stage2_f1_s2_root279_native_scalar_parent_worker_v1.py"
COMPACT_V2_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v2.py"
SCALAR_PATH = HERE / "stage2_rotation_invariant_native_scalar_observer_v2.py"
VERIFIER_PATH = HERE / "stage2_f1_s2_root279_native_scalar_verify_v1.py"
SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-worker.v2"
MANIFEST_SCHEMAS = {"ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v1",
                    "ds02.stage2.f1-s2.root279-native-scalar-parent-manifest.v2"}
COMPACT_RESULT_STATUS = "COMPLETE_ROOT279_NATIVE_COMPACT_REPORTS_NO_SCIENTIFIC_Q"
GUARD_STATUS = "PASS"


class ParentV2Failure(RuntimeError):
    pass


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ParentV2Failure(f"cannot load source-bound helper: {path}")
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


LEGACY = _load(LEGACY_PATH, "root279_parent_v1_for_v2")
COMPACT = _load(COMPACT_V2_PATH, "root279_compact_v2_for_parent")
SCALAR = _load(SCALAR_PATH, "root279_scalar_v2_for_parent")
VERIFIER = _load(VERIFIER_PATH, "root279_verifier_v1_for_parent")


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = LEGACY._abs(path)
    if path.exists() or path.is_symlink():
        raise ParentV2Failure(f"refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    return LEGACY._read(path, label)


def _run(command: list[str], *, cwd: Path, timeout: float, label: str) -> tuple[int, str, str]:
    return LEGACY._run(command, cwd=cwd, timeout=timeout, label=label)


def _sealed_manifest(template: dict[str, Any], compact_result: dict[str, Any], path: Path) -> tuple[Path, dict[str, Any]]:
    reports = compact_result.get("compact_reports")
    if not isinstance(reports, dict) or set(reports) != {"same_cfl", "half_cfl"}:
        raise ParentV2Failure("compact result lacks exactly two sealed compact_reports")
    sealed = dict(template)
    sealed["schema"] = "ds02.stage2.f1-s2.root279-native-compact-manifest.v1"
    sealed["status"] = "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT"
    sealed["outputs"] = reports
    sealed["sealed_result"] = compact_result.get("result") or {"status": compact_result.get("status")}
    _write_once(path, sealed)
    return path, LEGACY._record(path, "sealed ROOT279 compact manifest")


def run(manifest_path: Path, attempt_root: Path) -> dict[str, Any]:
    template, template_record = _read(manifest_path, "ROOT279 scalar parent V2 manifest")
    if template.get("schema") not in MANIFEST_SCHEMAS:
        raise ParentV2Failure("parent manifest schema mismatch")
    if template.get("status") not in {"READY_FOR_PARENT_ROOT279_NATIVE_SCALAR", "WAITING_PARENT_ROOT279_NATIVE_SCALAR"}:
        raise ParentV2Failure("parent manifest is not parent-ready")
    attempt_root = LEGACY._abs(attempt_root); attempt_root.mkdir(parents=True, exist_ok=True)
    config = template.get("runtime")
    if not isinstance(config, dict):
        raise ParentV2Failure("parent manifest lacks runtime configuration")
    python = LEGACY._abs(config.get("literal_python"))
    guard = LEGACY._abs(config.get("guard_worker"))
    v1_worker = LEGACY._abs(config.get("native_child_worker"))
    compact_worker = LEGACY._abs(config.get("compact_worker"))
    scalar_worker = LEGACY._abs(config.get("scalar_worker"))
    verifier = LEGACY._abs(config.get("verifier"))
    root279_manifest = LEGACY._abs(config.get("root279_manifest"))
    root279_bridge = LEGACY._abs(config.get("root279_bridge"))
    cwd = LEGACY._abs(config.get("cwd"))
    for path, label in ((python, "literal Python"), (guard, "ROOT279 guard"),
                        (v1_worker, "native child worker"), (scalar_worker, "scalar worker"),
                        (verifier, "scalar verifier"), (root279_manifest, "ROOT279 source manifest"),
                        (root279_bridge, "ROOT279 v3-to-v2 bridge")):
        if not path.exists():
            raise ParentV2Failure(f"{label} is unavailable: {path}")
    # A V2 request must bind the additive compact worker.  A legacy path is
    # rejected rather than silently using the broken V1 chain.
    if compact_worker != COMPACT_V2_PATH.absolute():
        raise ParentV2Failure(f"parent V2 compact worker is not additive V2: {compact_worker}")
    observer_dir = attempt_root / "observer"; observer_dir.mkdir(parents=True, exist_ok=True)
    guard_output = observer_dir / "root279-guard-result.json"
    guard_log = observer_dir / "root279-guard.log"
    projected_manifest, projection_record = LEGACY._prepare_legacy_guard_manifest(root279_manifest, attempt_root, root279_bridge)
    guard_command = [str(python), str(guard), "--run", "--manifest", str(projected_manifest),
                     "--attempt-root", str(attempt_root), "--output", str(guard_output),
                     "--log-path", str(guard_log), "--v1-worker", str(v1_worker),
                     "--python", str(python), "--cwd", str(cwd),
                     "--max-scratch-bytes", str(config.get("max_scratch_bytes", 256 * 1024 * 1024)),
                     "--max-log-bytes", str(config.get("max_log_bytes", 1024 * 1024)),
                     "--timeout-seconds", str(config.get("guard_timeout_seconds", 1800))]
    _run(guard_command, cwd=cwd, timeout=float(config.get("guard_timeout_seconds", 1800)) + 30,
         label="ROOT279 guarded producer")
    guard_value, guard_record = _read(guard_output, "ROOT279 guard output")
    if guard_value.get("status") != GUARD_STATUS:
        raise ParentV2Failure("ROOT279 guarded producer did not return exact PASS")
    child_output = observer_dir / ".v1-result.json"
    if not child_output.is_file():
        child_ref = guard_value.get("child_output")
        if isinstance(child_ref, dict) and isinstance(child_ref.get("path"), str):
            child_output = LEGACY._abs(child_ref["path"])
    if not child_output.is_file():
        raise ParentV2Failure("ROOT279 guard did not produce child observer JSON")
    child_value, child_record = _read(child_output, "ROOT279 child observer output")
    if child_value.get("status") != "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES":
        raise ParentV2Failure("ROOT279 child observer status is not exact native PASS")
    compact_manifest = LEGACY._replace_attempt(template["compact_manifest"], attempt_root)
    compact_manifest_path = observer_dir / "compact-manifest.json"
    compact_manifest["guard_result"] = guard_record; compact_manifest["child_report"] = child_record
    compact_manifest["status"] = "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT"
    compact_manifest["result_path"] = str(observer_dir / "compact/root279-native-compact-result.json")
    _write_once(compact_manifest_path, compact_manifest)
    compact_output_dir = observer_dir / "compact"; compact_output_dir.mkdir(parents=True, exist_ok=True)
    _run([str(python), str(compact_worker), "--run", "--manifest", str(compact_manifest_path),
          "--output-dir", str(compact_output_dir)], cwd=cwd,
         timeout=float(config.get("compact_timeout_seconds", 300)), label="ROOT279 compact V2 producer")
    compact_result_path = LEGACY._abs(compact_manifest["result_path"])
    compact_result, compact_result_record = _read(compact_result_path, "ROOT279 sealed compact result")
    if compact_result.get("status") != COMPACT_RESULT_STATUS:
        raise ParentV2Failure("compact V2 result status is not exact")
    compact_reports = compact_result.get("compact_reports")
    if not isinstance(compact_reports, dict) or set(compact_reports) != {"same_cfl", "half_cfl"}:
        raise ParentV2Failure("compact V2 result has no two sealed report records")
    sealed_path, sealed_record = _sealed_manifest(compact_manifest, compact_result, observer_dir / "compact/compact-sealed-manifest.json")
    scalar_manifest = LEGACY._replace_attempt(template["scalar_manifest"], attempt_root)
    scalar_manifest_path = observer_dir / "scalar-manifest.json"
    scalar_manifest["attempts"] = []
    for label, attempt_id in (("same_cfl", "root279-same-cfl"), ("half_cfl", "root279-half-cfl")):
        record = compact_reports[label]
        if not isinstance(record, dict) or not isinstance(record.get("path"), str) or not record.get("sha256"):
            raise ParentV2Failure(f"compact V2 sealed record missing for {label}")
        scalar_manifest["attempts"].append({
            "label": label, "attempt_id": attempt_id, "rows_key": "observations",
            "source_identity_digest": scalar_manifest["source_identity"]["source_identity_digest"],
            "report": record,
        })
    _write_once(scalar_manifest_path, scalar_manifest)
    scalar_output_path = observer_dir / "scalar-result.json"
    _run([str(python), str(scalar_worker), "--run", "--manifest", str(scalar_manifest_path),
          "--output", str(scalar_output_path)], cwd=cwd,
         timeout=float(config.get("scalar_timeout_seconds", 300)), label="ROOT279 scalar consumer")
    verification_output = observer_dir / "scalar-verification.json"
    _run([str(python), str(verifier), "--verify", "--compact-manifest", str(sealed_path),
          "--scalar-manifest", str(scalar_manifest_path), "--scalar-output", str(scalar_output_path),
          "--verification-output", str(verification_output)], cwd=cwd,
         timeout=float(config.get("verify_timeout_seconds", 300)), label="ROOT279 independent scalar verifier")
    _, scalar_record = _read(scalar_output_path, "ROOT279 scalar result")
    _, verification_record = _read(verification_output, "ROOT279 scalar verification")
    result = {
        "schema": SCHEMA, "status": "COMPLETE_ROOT279_NATIVE_PRODUCER_COMPACT_V2_SCALAR_VERIFIER_CHAIN_NO_SCIENTIFIC_Q",
        "guard_result": guard_record, "child_report": child_record,
        "root279_projection": projection_record, "compact_result": compact_result_record,
        "compact_sealed_manifest": sealed_record, "scalar_manifest": LEGACY._record(scalar_manifest_path, "scalar manifest"),
        "scalar_result": scalar_record, "verification": verification_record,
        "read_scope": {"native_reader": "ROOT279 guarded producer only", "compact_json_consumer": True,
                        "native_payload_read_by_wrapper": False, "solver_launch": False, "gencase_launch": False},
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0},
    }
    _write_once(observer_dir / "root279-native-scalar-parent-result-v2.json", result)
    return result


def _self_test() -> None:
    """Exercise child -> compact V2 -> scalar -> independent verifier on tiny JSON."""
    with tempfile.TemporaryDirectory(prefix="root279-parent-v2-chain-") as value:
        root = Path(value)
        guard, child = COMPACT.V1._fixture_child(root)
        guard_value = json.loads(guard.read_text(encoding="utf-8"))
        guard_value["status"] = COMPACT.GUARD_STATUS
        guard.write_text(json.dumps(guard_value, sort_keys=True) + "\n", encoding="utf-8")
        child_value = json.loads(child.read_text(encoding="utf-8")); child_value["status"] = COMPACT.CHILD_STATUS
        child.write_text(json.dumps(child_value) + "\n", encoding="utf-8")
        guard_rec = COMPACT.V1._record_json(guard, "fixture guard")[1]
        child_rec = COMPACT.V1._record_json(child, "fixture child")[1]
        identity = "fixture-root279-parent-v2-identity"
        compact_manifest = {"schema": COMPACT.V1.MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                           "source_identity_digest": identity, "guard_result": guard_rec, "child_report": child_rec,
                           "outputs": {label: {"path": str(root / f"{label}.json")} for label in ("same_cfl", "half_cfl")},
                           "result_path": str(root / "compact-result.json")}
        compact_path = root / "compact-manifest.json"; compact_path.write_text(json.dumps(compact_manifest) + "\n")
        compact_result = COMPACT.run(compact_path)
        sealed_path, _ = _sealed_manifest(compact_manifest, compact_result, root / "sealed-manifest.json")
        scalar_manifest = {"schema": SCALAR.MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
                           "source_identity": {"source_identity_digest": identity, "component_basis": "PRODUCER_COMPONENT_XYZ",
                                               "world_orientation": "UNKNOWN", "world_directional_claims": False,
                                               "flux_claims": False, "owner_mass_claims": False},
                           "attempts": [{"label": "same-cfl", "attempt_id": "same", "rows_key": "observations",
                                         "source_identity_digest": identity, "report": compact_result["compact_reports"]["same_cfl"]},
                                        {"label": "half-cfl", "attempt_id": "half", "rows_key": "observations",
                                         "source_identity_digest": identity, "report": compact_result["compact_reports"]["half_cfl"]}],
                           "query_times_s": [0.0, 0.25, 0.5]}
        scalar_path = root / "scalar-manifest.json"; scalar_path.write_text(json.dumps(scalar_manifest) + "\n")
        scalar_output = root / "scalar.json"; SCALAR.run(scalar_path, scalar_output)
        verification = VERIFIER.verify(sealed_path, scalar_path, scalar_output)
        assert verification["scientific_qualification"]["scientific_credit"] == 0
        assert compact_result["compact_reports"]["same_cfl"]["sha256"]
    print("PASS_ROOT279_FULL_V2_CHILD_COMPACT_SCALAR_VERIFIER_CHAIN_TINY_NO_PRODUCTION_CREDIT")


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
        run(args.manifest, args.attempt_root)
        return 0
    except (ParentV2Failure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_SCALAR_PARENT_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
