#!/usr/bin/env python3
"""ROOT279 scalar parent with the real guarded-wrapper status ABI.

ROOT353 reached the native guard and sealed all ten sources, but the consumed
parent V2 compared the wrapper's real
``PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES`` result with the legacy literal
``PASS`` and stopped before compact/scalar consumption.  This additive worker
keeps the V2 parent flow, compact/scalar/verifier joins, and no-scientific-Q
scope, while allowing only the two observed wrapper PASS statuses.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_f1_s2_root279_native_scalar_parent_worker_v2.py"
COMPACT_V3_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v3.py"
SCHEMA = "ds02.stage2.f1-s2.root279-native-scalar-parent-worker.v3"
GUARD_STATUSES = frozenset({"PASS", "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"})

SPEC = importlib.util.spec_from_file_location("root279_scalar_parent_v2_for_v3", V2_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load scalar parent V2: {V2_PATH}")
V2 = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(V2)
COMPACT_SPEC = importlib.util.spec_from_file_location("root279_compact_v3_for_parent_v3", COMPACT_V3_PATH)
if COMPACT_SPEC is None or COMPACT_SPEC.loader is None:
    raise RuntimeError(f"cannot load compact V3: {COMPACT_V3_PATH}")
COMPACT = importlib.util.module_from_spec(COMPACT_SPEC); COMPACT_SPEC.loader.exec_module(COMPACT)


class ParentV3Failure(RuntimeError):
    pass


class _AllowedGuardStatus:
    """Equality proxy for the frozen V2 exact comparison, with no prefix gate."""
    def __eq__(self, value: object) -> bool:
        return value in GUARD_STATUSES

    def __repr__(self) -> str:
        return "AllowedGuardStatuses(" + ",".join(sorted(GUARD_STATUSES)) + ")"


def _configure() -> None:
    # V2.run reads these globals at call time.  The proxy changes only the
    # status equality edge; all downstream source and result joins remain V2.
    V2.COMPACT = COMPACT
    V2.COMPACT_V2_PATH = COMPACT_V3_PATH.absolute()
    V2.GUARD_STATUS = _AllowedGuardStatus()
    V2.SCHEMA = SCHEMA


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ParentV3Failure(f"worker result is not an object: {path}")
    return value


def run(manifest_path: Path, attempt_root: Path) -> dict[str, Any]:
    _configure()
    result = V2.run(manifest_path, attempt_root)
    result = dict(result)
    result["schema"] = SCHEMA
    result["status"] = "COMPLETE_ROOT279_NATIVE_PRODUCER_COMPACT_V3_SCALAR_VERIFIER_CHAIN_NO_SCIENTIFIC_Q"
    result["guard_status_allowlist"] = sorted(GUARD_STATUSES)
    result["guard_status_basis"] = result.get("guard_result", {}).get("status")
    result["compact_worker_schema"] = COMPACT.SCHEMA
    result["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
    result["read_scope"] = {"native_reader": "ROOT279 guarded producer only", "compact_json_consumer": True,
                             "native_payload_read_by_wrapper": False, "solver_launch": False, "gencase_launch": False}
    root = Path(attempt_root).expanduser().absolute() / "observer"
    legacy_result = root / "root279-native-scalar-parent-result-v2.json"
    output = root / "root279-native-scalar-parent-result-v3.json"
    if legacy_result.is_file():
        # The V2 file is an internal immutable trace; V3 is the parent-facing
        # result and carries the corrected status contract.
        payload = _read_json(legacy_result)
        payload.update({"schema": SCHEMA, "status": result["status"],
                        "guard_status_allowlist": sorted(GUARD_STATUSES),
                        "guard_status_basis": result["guard_status_basis"],
                        "compact_worker_schema": COMPACT.SCHEMA,
                        "scientific_qualification": result["scientific_qualification"]})
        if output.exists() or output.is_symlink():
            raise ParentV3Failure(f"refusing overwrite V3 result: {output}")
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result["parent_result_v3"] = {"path": str(output), "sha256": V2.LEGACY._sha(output.read_bytes()),
                                      "stat": V2.LEGACY._stat(output)}
    return result


def _self_test() -> None:
    # Run the actual ROOT279 guarded wrapper against temporary BI4-like files,
    # then feed its real guard/child JSON to compact, scalar, and verifier.
    # The child executable is manufactured only to supply the tiny typed rows;
    # the guard itself performs its real pre/post hashing, scratch, cancellation
    # and child boundary logic.
    guard_spec = HERE / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"
    guard_import = importlib.util.spec_from_file_location("root279_pair_guard_fixture_v3", guard_spec)
    if guard_import is None or guard_import.loader is None:
        raise AssertionError(f"missing guarded producer fixture: {guard_spec}")
    guard_module = importlib.util.module_from_spec(guard_import); guard_import.loader.exec_module(guard_module)
    guard_module._configure()
    with __import__("tempfile").TemporaryDirectory(prefix="root279-parent-v3-full-chain-") as value:
        root = Path(value)
        manifest, _ = guard_module.V4._fixture_manifest(root / "guarded")
        child_fixture_root = root / "child-fixture"; child_fixture_root.mkdir(parents=True, exist_ok=True)
        fixture_guard, fixture_child = V2.COMPACT.V1._fixture_child(child_fixture_root)
        child_value = json.loads(fixture_child.read_text(encoding="utf-8"))
        child_value["status"] = COMPACT.CHILD_STATUS
        child_payload = json.dumps(child_value, ensure_ascii=False, sort_keys=True)
        child_script = root / "child-fixture.py"
        child_script.write_text(
            "import argparse, json, pathlib\n"
            "p=argparse.ArgumentParser(); p.add_argument('--output'); p.add_argument('--manifest'); p.add_argument('--attempt-root'); a=p.parse_args()\n"
            f"payload={child_payload!r}\n"
            "pathlib.Path(a.output).parent.mkdir(parents=True, exist_ok=True)\n"
            "pathlib.Path(a.output).write_text(payload+'\\n')\n",
            encoding="utf-8")
        attempt = root / "guarded" / "attempt"
        guard_output = attempt / "observer" / "guard.json"
        args = argparse.Namespace(manifest=manifest, attempt_root=attempt, output=guard_output,
                                  log_path=attempt / "observer" / "guard.log", v1_worker=child_script,
                                  python=Path(guard_module.V4.PYTHON), cwd=root,
                                  max_scratch_bytes=guard_module.V4.SCRATCH_CAP_BYTES,
                                  max_log_bytes=guard_module.V4.DEFAULT_MAX_LOG_BYTES, timeout_seconds=10.0)
        guarded = guard_module.V4.run_guard(args)
        assert guarded["status"] == "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES", guarded
        actual_child = Path(guarded["child_output"]["path"])
        guard_record = COMPACT.V1._record_json(guard_output, "actual fixture guard")[1]
        child_record = COMPACT.V1._record_json(actual_child, "actual fixture child")[1]
        compact_manifest = {"schema": COMPACT.V1.MANIFEST_SCHEMA,
                            "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                            "source_identity_digest": "fixture-root279-v3-real-guard-identity",
                            "guard_result": guard_record, "child_report": child_record,
                            "outputs": {label: {"path": str(root / f"{label}.json")}
                                        for label in ("same_cfl", "half_cfl")},
                            "result_path": str(root / "compact-result.json")}
        compact_path = root / "compact-manifest.json"
        compact_path.write_text(json.dumps(compact_manifest) + "\n", encoding="utf-8")
        compact_result = COMPACT.run(compact_path)
        sealed_path, _ = V2._sealed_manifest(compact_manifest, compact_result, root / "sealed-manifest.json")
        scalar_manifest = {"schema": V2.SCALAR.MANIFEST_SCHEMA,
                           "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
                           "source_identity": {"source_identity_digest": compact_manifest["source_identity_digest"],
                                               "component_basis": "PRODUCER_COMPONENT_XYZ",
                                               "world_orientation": "UNKNOWN", "world_directional_claims": False,
                                               "flux_claims": False, "owner_mass_claims": False},
                           "attempts": [{"label": label.replace("_", "-"), "attempt_id": label,
                                         "rows_key": "observations",
                                         "source_identity_digest": compact_manifest["source_identity_digest"],
                                         "report": compact_result["compact_reports"][label]}
                                        for label in ("same_cfl", "half_cfl")],
                           "query_times_s": [0.0, 0.25, 0.5]}
        scalar_path = root / "scalar-manifest.json"; scalar_path.write_text(json.dumps(scalar_manifest) + "\n")
        scalar_output = root / "scalar.json"; V2.SCALAR.run(scalar_path, scalar_output)
        verification = V2.VERIFIER.verify(sealed_path, scalar_path, scalar_output)
        assert verification["scientific_qualification"]["scientific_credit"] == 0
        assert compact_result["guard_status_basis"] == "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
    assert COMPACT.GUARD_STATUSES == GUARD_STATUSES
    print("PASS_ROOT279_SCALAR_PARENT_V3_GUARD_STATUS_COMPATIBILITY_FULL_CHAIN_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--attempt-root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None or args.attempt_root is None:
            parser.error("--run requires --manifest and --attempt-root")
        value = run(args.manifest, args.attempt_root)
        print(json.dumps({"status": value["status"], "guard_status": value.get("guard_status_basis"),
                          "scientific_credit": 0}, sort_keys=True)); return 0
    except (ParentV3Failure, V2.ParentV2Failure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_SCALAR_PARENT_V3: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
