#!/usr/bin/env python3
"""ROOT279 compact worker with the actual guarded-wrapper status contract.

The consumed V2 compact worker accepted only ``PASS`` from the wrapper.  The
actual ROOT279 V3 guard returns ``PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES``
after its deferred pre/post source checks, while the child observer keeps its
own ``PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES`` status.  This additive
worker accepts exactly those two wrapper statuses (and the legacy ``PASS``),
then delegates all typed-role, native-mass, and compact-report logic to the
frozen V1 implementation.  It never opens native payloads.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v2.py"
V1_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v1.py"
V2_SPEC = importlib.util.spec_from_file_location("root279_compact_v2_for_v3", V2_PATH)
if V2_SPEC is None or V2_SPEC.loader is None:
    raise RuntimeError(f"cannot load compact V2: {V2_PATH}")
V2 = importlib.util.module_from_spec(V2_SPEC); V2_SPEC.loader.exec_module(V2)
V1 = V2.V1

SCHEMA = "ds02.stage2.f1-s2.root279-native-compact-worker.v3"
GUARD_STATUSES = frozenset({"PASS", "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"})
# Compatibility name used by the frozen V2 manufactured-chain fixture.  The
# runtime worker still validates the full allow-list above.
GUARD_STATUS = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
CHILD_STATUS = "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES"
OUTPUT_STATUS = "COMPLETE_ROOT279_NATIVE_COMPACT_REPORTS_V3_NO_SCIENTIFIC_Q"


class CompactV3Failure(RuntimeError):
    pass


def _run_status(guard: dict[str, Any], label: str) -> str:
    if guard.get("schema") != V1.GUARD_SCHEMA or guard.get("status") not in GUARD_STATUSES:
        raise CompactV3Failure(f"{label} guard schema/status is not one of the exact guarded PASS statuses")
    return str(guard["status"])


def run(manifest_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = V1._record_json(manifest_path, "ROOT279 compact V3 manifest")
    if manifest.get("schema") not in {V1.MANIFEST_SCHEMA, "ds02.stage2.f1-s2.root279-native-compact-manifest.v2"}:
        raise CompactV3Failure("compact manifest schema mismatch")
    if manifest.get("status") not in {"READY_FOR_PARENT_ROOT279_NATIVE_COMPACT", "WAITING_PARENT_ROOT279_NATIVE_COMPACT"}:
        raise CompactV3Failure("compact manifest is not parent-ready")
    identity = manifest.get("source_identity_digest")
    if not isinstance(identity, str) or len(identity) < 16 or identity in {V1.UNKNOWN, "PARENT_AFTER_RESERVATION_REQUIRED"}:
        raise CompactV3Failure("compact source identity is not bound")
    guard_ref, child_ref = manifest.get("guard_result"), manifest.get("child_report")
    guard, guard_record = V1._record_json(Path(guard_ref["path"]), "ROOT279 guarded result", guard_ref)
    child, child_record = V1._record_json(Path(child_ref["path"]), "ROOT279 child observer result", child_ref)
    guard_status = _run_status(guard, "ROOT279")
    if child.get("schema") != V1.CHILD_SCHEMA or child.get("status") != CHILD_STATUS:
        raise CompactV3Failure("ROOT279 child schema/status is not exact native-observer PASS")
    output_paths = manifest.get("outputs")
    if not isinstance(output_paths, dict):
        raise CompactV3Failure("compact manifest has no output paths")
    cases = V1._case_map(child)
    outputs: dict[str, dict[str, Any]] = {}
    for label in ("same_cfl", "half_cfl"):
        ref = output_paths.get(label)
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise CompactV3Failure(f"compact output path missing for {label}")
        report = V1._case_report(label, cases[label], identity, guard_record, child_record)
        V1._write_once(Path(ref["path"]), report)
        _, output_record = V1._record_json(Path(ref["path"]), f"{label} compact V3 output")
        outputs[label] = output_record
    result = {
        # Keep the consumed compact report schema so the independent V1
        # verifier remains the downstream semantic checker.
        "schema": "ds02.stage2.f1-s2.root279-native-compact-worker.v1",
        "status": "COMPLETE_ROOT279_NATIVE_COMPACT_REPORTS_NO_SCIENTIFIC_Q",
        "manifest": manifest_record, "guard_result": guard_record, "child_report": child_record,
        "compact_reports": outputs, "source_identity_digest": identity,
        "guard_status_basis": guard_status, "accepted_guard_statuses": sorted(GUARD_STATUSES),
        "child_status_basis": CHILD_STATUS,
        "native_header_semantics": "MassFluid/MassBound are per-particle; sample total requires typed counts or per-ID weights",
        "scientific_qualification": dict(V1.QUALIFICATION),
        "read_scope": {"guard_child_json_only": True, "native_payload_read": False,
                        "solver_launch": False, "gencase_launch": False},
    }
    result_path = manifest.get("result_path")
    if isinstance(result_path, str):
        V1._write_once(Path(result_path), result)
        result["result"] = V1._record_json(Path(result_path), "compact V3 sealed result")[1]
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-compact-v3-") as value:
        root = Path(value)
        guard, child = V1._fixture_child(root)
        guard_value = json.loads(guard.read_text(encoding="utf-8")); guard_value["status"] = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
        guard.write_text(json.dumps(guard_value, sort_keys=True) + "\n", encoding="utf-8")
        child_value = json.loads(child.read_text(encoding="utf-8")); child_value["status"] = CHILD_STATUS
        child.write_text(json.dumps(child_value, sort_keys=True) + "\n", encoding="utf-8")
        guard_record = V1._record_json(guard, "fixture guard")[1]; child_record = V1._record_json(child, "fixture child")[1]
        manifest = {"schema": V1.MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                    "source_identity_digest": "fixture-root279-v3-identity", "guard_result": guard_record,
                    "child_report": child_record, "outputs": {label: {"path": str(root / f"{label}.json")}
                                                                  for label in ("same_cfl", "half_cfl")},
                    "result_path": str(root / "compact-result.json")}
        path = root / "manifest.json"; path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        result = run(path)
        assert result["guard_status_basis"] == "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
        assert result["compact_reports"]["same_cfl"]["sha256"]
        bad = dict(guard_value, status="PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES_BOGUS")
        bad_path = root / "bad-guard.json"; bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        bad_manifest = dict(manifest, guard_result={**guard_record, "path": str(bad_path),
                                                     "sha256": V1._sha(bad_path.read_bytes()), "stat": V1._stat(bad_path)})
        bad_manifest_path = root / "bad-manifest.json"; bad_manifest_path.write_text(json.dumps(bad_manifest) + "\n")
        try:
            run(bad_manifest_path)
        except CompactV3Failure:
            pass
        else:
            raise AssertionError("unknown guard status was accepted")
    print("PASS_ROOT279_COMPACT_V3_ACTUAL_GUARD_STATUS_AND_TYPED_REPORT_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path); parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None:
            parser.error("--run requires --manifest")
        value = run(args.manifest, args.output_dir)
        print(json.dumps({"status": value["status"], "scientific_credit": 0}, sort_keys=True)); return 0
    except (CompactV3Failure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_COMPACT_V3: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
