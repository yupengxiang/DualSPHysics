#!/usr/bin/env python3
"""ROOT279 compact adapter with the real child-observer status edge.

This is an additive compatibility version of the consumed compact worker.
The guarded wrapper has status ``PASS`` while the frozen native observer
reports ``PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES``.  V1 compared both
documents to the wrapper status and therefore rejected a real child.  V2
keeps the V1 report/manifest schemas for the independent verifier, but uses
the two exact statuses and seals output SHA/stat records in the result
document.  It reads only the guard/child JSON; the guarded producer remains
the only native-payload reader.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V1_PATH = HERE / "stage2_f1_s2_root279_native_compact_worker_v1.py"
GUARD_STATUS = "PASS"
CHILD_STATUS = "PASS_F1_NATIVE_HEADER_SELECTED_OBSERVABLES"
OUTPUT_STATUS = "COMPLETE_ROOT279_NATIVE_COMPACT_REPORTS_NO_SCIENTIFIC_Q"


class CompactV2Failure(RuntimeError):
    pass


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("root279_compact_v1_for_v2", V1_PATH)
    if spec is None or spec.loader is None:
        raise CompactV2Failure(f"cannot load consumed compact worker: {V1_PATH}")
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


V1 = _load_v1()


def run(manifest_path: Path, output_dir: Path | None = None) -> dict[str, Any]:
    manifest, manifest_record = V1._record_json(manifest_path, "ROOT279 compact V2 manifest")
    if manifest.get("schema") not in {V1.MANIFEST_SCHEMA, "ds02.stage2.f1-s2.root279-native-compact-manifest.v2"}:
        raise CompactV2Failure("compact manifest schema mismatch")
    if manifest.get("status") not in {"READY_FOR_PARENT_ROOT279_NATIVE_COMPACT", "WAITING_PARENT_ROOT279_NATIVE_COMPACT"}:
        raise CompactV2Failure("compact manifest is not parent-ready")
    source_digest = manifest.get("source_identity_digest")
    if not isinstance(source_digest, str) or len(source_digest) < 16 or source_digest in {V1.UNKNOWN, "PARENT_AFTER_RESERVATION_REQUIRED"}:
        raise CompactV2Failure("compact source identity is not bound")
    guard_ref, child_ref = manifest.get("guard_result"), manifest.get("child_report")
    guard, guard_record = V1._record_json(Path(guard_ref["path"]), "ROOT279 guarded result", guard_ref)
    child, child_record = V1._record_json(Path(child_ref["path"]), "ROOT279 child observer result", child_ref)
    if guard.get("schema") != V1.GUARD_SCHEMA or guard.get("status") != GUARD_STATUS:
        raise CompactV2Failure("ROOT279 guard schema/status is not exact PASS")
    if child.get("schema") != V1.CHILD_SCHEMA or child.get("status") != CHILD_STATUS:
        raise CompactV2Failure("ROOT279 child schema/status is not exact native-observer PASS")
    output_paths = manifest.get("outputs")
    if not isinstance(output_paths, dict):
        raise CompactV2Failure("compact manifest has no output paths")
    cases = V1._case_map(child)
    outputs: dict[str, dict[str, Any]] = {}
    for label in ("same_cfl", "half_cfl"):
        ref = output_paths.get(label)
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise CompactV2Failure(f"compact output path missing for {label}")
        report = V1._case_report(label, cases[label], source_digest, guard_record, child_record)
        V1._write_once(Path(ref["path"]), report)
        _, output_record = V1._record_json(Path(ref["path"]), f"{label} compact V2 output")
        outputs[label] = output_record
    result = {
        # Keep the V1 result schema so the independent consumed verifier can
        # read this additive worker without a schema alias or a hidden bypass.
        "schema": "ds02.stage2.f1-s2.root279-native-compact-worker.v1",
        "status": OUTPUT_STATUS,
        "manifest": manifest_record, "guard_result": guard_record, "child_report": child_record,
        "compact_reports": outputs, "source_identity_digest": source_digest,
        "child_status_basis": CHILD_STATUS,
        "guard_status_basis": GUARD_STATUS,
        "native_header_semantics": "MassFluid/MassBound are per-particle; sample total requires typed counts or per-ID weights",
        "scientific_qualification": dict(V1.QUALIFICATION),
        "read_scope": {"guard_child_json_only": True, "native_payload_read": False,
                        "solver_launch": False, "gencase_launch": False},
    }
    result_path = manifest.get("result_path")
    if isinstance(result_path, str):
        V1._write_once(Path(result_path), result)
        result["result"] = V1._record_json(Path(result_path), "compact V2 sealed result")[1]
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-compact-v2-") as value:
        root = Path(value)
        guard, child = V1._fixture_child(root)
        guard_value = json.loads(guard.read_text(encoding="utf-8"))
        guard_value["status"] = GUARD_STATUS
        guard.write_text(json.dumps(guard_value, sort_keys=True) + "\n", encoding="utf-8")
        child_value = json.loads(child.read_text(encoding="utf-8"))
        child_value["status"] = CHILD_STATUS
        child.write_text(json.dumps(child_value, sort_keys=True) + "\n", encoding="utf-8")
        guard_record = V1._record_json(guard, "fixture guard")[1]
        child_record = V1._record_json(child, "fixture child")[1]
        manifest = {"schema": V1.MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                    "source_identity_digest": "fixture-root279-source-identity",
                    "guard_result": guard_record, "child_report": child_record,
                    "outputs": {label: {"path": str(root / f"{label}.json")} for label in ("same_cfl", "half_cfl")},
                    "result_path": str(root / "compact-result.json")}
        manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        result = run(manifest_path, root / "outputs")
        assert result["status"] == OUTPUT_STATUS
        assert result["child_status_basis"] == CHILD_STATUS
        for label in ("same_cfl", "half_cfl"):
            assert result["compact_reports"][label]["sha256"]
            assert result["compact_reports"][label]["stat"]["bytes"] > 0
        # The old wrapper status on a child is rejected; this prevents a
        # future broad startswith gate from silently reintroducing the bug.
        bad = json.loads(child.read_text(encoding="utf-8")); bad["status"] = GUARD_STATUS
        bad_path = root / "bad-child.json"; bad_path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
        bad_manifest = dict(manifest, child_report={**child_record, "path": str(bad_path),
                                                     "sha256": V1._sha(bad_path.read_bytes()),
                                                     "stat": V1._stat(bad_path)})
        bad_manifest_path = root / "bad-manifest.json"; bad_manifest_path.write_text(json.dumps(bad_manifest) + "\n")
        try:
            run(bad_manifest_path)
        except CompactV2Failure:
            pass
        else:
            raise AssertionError("wrapper PASS was accepted as child status")
    print("PASS_ROOT279_COMPACT_V2_REAL_CHILD_STATUS_AND_SEALED_OUTPUT_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None:
            parser.error("--run requires --manifest")
        run(args.manifest, args.output_dir)
        return 0
    except (CompactV2Failure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_COMPACT_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
