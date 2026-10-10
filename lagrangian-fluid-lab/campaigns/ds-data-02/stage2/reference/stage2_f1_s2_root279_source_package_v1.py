#!/usr/bin/env python3
"""Prepare a ROOT279 source package from the actual ROOT310 snapshot.

This is an additive source packager.  It reads the ROOT310 verification JSON,
its small snapshot report, the ROOT277/278 terminal proofs, and small source
closure files.  It never opens a Part_*.bi4 file.  The resulting manifest and
request are deliberately ``WAITING_PARENT...`` and cannot be submitted as a
completed scientific observation: the future ROOT279 wrapper must recheck all
ten native files before and after the decoder under its own reservation.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.f1.root279-source-package.v1"
SMALL_LIMIT = 10 * 1024 * 1024
PROOF_SHA = {
    "same": "026b2d326c2d65869dc16c6a0d062056ca31d720642dbb715bd3d13d787115d8",
    "half": "b357afa839d78bf8a8e14626e459f79c08afd77c739c078e2f13573ee3871629",
    "root310": "14ac610d5c87e2aabe0c65bdadefe9a17530ff3dc0719245def0408b58701c23",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stat_record(path: Path) -> dict[str, int]:
    s = path.stat()
    return {
        "bytes": int(s.st_size),
        "device": int(s.st_dev),
        "inode": int(s.st_ino),
        "mtime_ns": int(s.st_mtime_ns),
        "ctime_ns": int(s.st_ctime_ns),
    }


def source_record(path: Path, *, declared_sha: str | None = None) -> dict[str, Any]:
    path = path.expanduser().absolute()
    before = stat_record(path)
    if before["bytes"] > SMALL_LIMIT:
        raise ValueError(f"source metadata exceeds 10 MiB cap: {path}")
    digest = sha256(path)
    after = stat_record(path)
    if before != after:
        raise ValueError(f"source changed while hashed: {path}")
    if declared_sha is not None and digest != declared_sha:
        raise ValueError(f"source SHA mismatch: {path}: {digest} != {declared_sha}")
    return {
        "path": str(path),
        "sha256": digest,
        "stat_before": before,
        "stat_after": after,
        "payload_read": True,
        "scope": "bounded_small_metadata_or_code",
    }


def load_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8")), source_record(path)


def _proof_record(path: Path, expected_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    proof, rec = load_json(path)
    if rec["sha256"] != expected_sha:
        raise ValueError(f"proof SHA mismatch: {path}")
    if proof.get("status", "").startswith("VERIFIED_ACTUAL") is False:
        raise ValueError(f"proof is not terminal verified: {path}: {proof.get('status')}")
    return proof, rec


def _replace_selected_records(
    old_case: dict[str, Any],
    snapshot_case: dict[str, Any],
) -> dict[str, Any]:
    """Replace placeholder native records with ROOT310-established metadata."""

    case = copy.deepcopy(old_case)
    by_frame = {int(x["frame"]): x for x in snapshot_case["selected_native_files"]}
    updated = []
    for old in case["selected_native_frame_metadata"]:
        frame = int(old["frame"])
        if frame not in by_frame:
            raise ValueError(f"ROOT310 snapshot is missing frame {frame}")
        got = by_frame[frame]
        if got["path"] != old["path"]:
            raise ValueError(f"ROOT310 path mismatch for frame {frame}")
        updated.append(
            {
                "frame": frame,
                "time_s": old["time_s"],
                "path": got["path"],
                "bytes": got["bytes"],
                "known_sha256": got["sha256"],
                "stat_before": got["stat_before"],
                "stat_after": got["stat_after"],
                "stat_consistency": got["stat_consistency"],
                "source_basis": "ROOT310_PARENT_AFTER_RESERVATION_SINGLE_STREAM",
            }
        )
    case["selected_native_frame_metadata"] = updated
    case["selected_frames"] = [int(x["frame"]) for x in updated]
    case["native_source_snapshot"] = {
        "proof_sha256": PROOF_SHA["root310"],
        "report_sha256": snapshot_case["selected_source_sha256"],
        "selected_native_bytes": snapshot_case["selected_native_bytes"],
        "selected_file_count": len(updated),
        "payload_read_by_packager": False,
    }
    return case


def build_package(primary_root: Path, output_dir: Path) -> dict[str, Any]:
    ref = primary_root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
    checkpoints = primary_root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints"
    request_root = primary_root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests"

    root310_proof_path = checkpoints / "F1_S2_TEN_SELECTED_SOURCE_SNAPSHOT_ACTUAL_ROOT_VERIFICATION_310.json"
    root310_proof, root310_proof_record = _proof_record(root310_proof_path, PROOF_SHA["root310"])
    root310_request_path = Path(root310_proof["request"])
    _, root310_request_record = load_json(root310_request_path)
    if root310_request_record["sha256"] != root310_proof["request_sha256"]:
        raise ValueError("ROOT310 proof/request SHA join failed")
    report_path = Path(root310_proof["report"])
    report, report_record = load_json(report_path)
    if report_record["sha256"] != root310_proof["report_sha256"]:
        raise ValueError("ROOT310 proof/report SHA join failed")
    if report.get("schema") != "ds02.stage2.native-source-snapshot.v2":
        raise ValueError("unexpected ROOT310 snapshot schema")
    if report.get("status") != "PASS_SELECTED_NATIVE_SOURCE_HASHED_STABLE":
        raise ValueError("ROOT310 snapshot is not stable")
    if report.get("selected_native_total_bytes") != root310_proof.get("selected_native_total_bytes"):
        raise ValueError("ROOT310 selected-byte count does not join proof")
    if len(report.get("immutable_source_sha_list", [])) != 10:
        raise ValueError("ROOT310 must supply exactly ten selected native files")

    proof_paths = {
        "same": checkpoints / "F1_S2_DP020_SAME_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_277.json",
        "half": checkpoints / "F1_S2_DP020_HALF_CFL_SAVEDT_BOUNDED_ACTUAL_ROOT_VERIFICATION_278.json",
    }
    proofs: dict[str, dict[str, Any]] = {}
    proof_records: dict[str, dict[str, Any]] = {}
    for label, path in proof_paths.items():
        proofs[label], proof_records[label] = _proof_record(path, PROOF_SHA[label])
        if proofs[label].get("scientific_qualification", {}).get("QI") != "UNKNOWN":
            raise ValueError(f"ROOT{label} proof unexpectedly grants QI")

    old_manifest_path = request_root / "root279-pair-native-source-v3-prepared-001/manifest.json"
    old_request_path = request_root / "root279-pair-native-source-v3-prepared-001/request.json"
    old_manifest, old_manifest_record = load_json(old_manifest_path)
    old_request, old_request_record = load_json(old_request_path)
    if old_manifest.get("schema") != "ds02.stage2.f1.native-selected-observer-manifest.v2":
        raise ValueError("unexpected frozen ROOT279 manifest schema")
    if old_request.get("schema") != "ds02.request.v1":
        raise ValueError("unexpected frozen ROOT279 request schema")
    if old_request.get("execution_allowed") is not False:
        raise ValueError("frozen ROOT279 source request is not source-only")

    # The actual snapshot report carries two requests in the same/half order.
    snapshot_cases = {x["case_id"]: x for x in report["requests"]}
    if set(snapshot_cases) != {
        "F1_S2_ROOT310_SAME_CFL_SELECTED_SOURCE_SNAPSHOT",
        "F1_S2_ROOT310_HALF_CFL_SELECTED_SOURCE_SNAPSHOT",
    }:
        raise ValueError("ROOT310 case set is not exactly same/half")

    manifest = copy.deepcopy(old_manifest)
    manifest["schema"] = "ds02.stage2.f1.native-selected-observer-manifest.v3-root310"
    manifest["status"] = "PREPARED_ROOT279_ROOT310_SNAPSHOT_BOUND_WAITING_PARENT_NATIVE_DECODE"
    manifest["source_pair"] = {
        **manifest.get("source_pair", {}),
        "root310_proof_sha256": PROOF_SHA["root310"],
        "root310_report_sha256": root310_proof["report_sha256"],
        "root310_request_sha256": root310_proof["request_sha256"],
        "same_proof_sha256": PROOF_SHA["same"],
        "same_request_sha256": proofs["same"]["request_sha256"],
        "half_proof_sha256": PROOF_SHA["half"],
        "half_request_sha256": proofs["half"]["request_sha256"],
        "root310_selected_source_sha_list_digest": report["source_sha_list_digest"],
    }
    for index, case in enumerate(manifest["cases"]):
        if case["label"] == "same_cfl":
            case = _replace_selected_records(case, snapshot_cases["F1_S2_ROOT310_SAME_CFL_SELECTED_SOURCE_SNAPSHOT"])
        elif case["label"] == "half_cfl":
            case = _replace_selected_records(case, snapshot_cases["F1_S2_ROOT310_HALF_CFL_SELECTED_SOURCE_SNAPSHOT"])
        else:
            raise ValueError(f"unexpected ROOT279 case label {case.get('label')}")
        # Replace the list element in place without changing its identity
        # contract or generated-XML provenance.
        manifest["cases"][index] = case

    native_records: dict[str, Any] = {}
    for snapshot_case in report["requests"]:
        for item in snapshot_case["selected_native_files"]:
            native_records[item["path"]] = {
                "path": item["path"],
                "frame": item["frame"],
                "bytes": item["bytes"],
                "known_sha256": item["sha256"],
                "time_s": next(
                    old["time_s"]
                    for c in old_manifest["cases"]
                    if (c["label"] == ("same_cfl" if "SAME" in snapshot_case["case_id"] else "half_cfl"))
                    for old in c["selected_native_frame_metadata"]
                    if old["frame"] == item["frame"]
                ),
                "stat_before": item["stat_before"],
                "stat_after": item["stat_after"],
                "stat_consistency": item["stat_consistency"],
                "source_basis": "ROOT310_PARENT_AFTER_RESERVATION_SINGLE_STREAM",
            }
    manifest["native_deferred_records"] = native_records
    manifest["native_deferred_policy"] = {
        "count": 10,
        "known_sha_required_before_child": True,
        "parent_after_reservation_first_sha_and_stat": True,
        "parent_after_child_post_sha_and_stat": True,
        "source_replace_or_stat_change": "FAIL",
        "full_native_tree_hash": "NOT_REQUESTED",
        "known_sha_basis": "ROOT310 snapshot, not a local prehash",
    }
    manifest["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

    # Preserve the frozen wrapper but point it at the stable new manifest.
    output_dir = output_dir.absolute()
    manifest_path = output_dir / "manifest.json"
    request_path = output_dir / "request.json"
    request = copy.deepcopy(old_request)
    request["status"] = "WAITING_PARENT_ROOT310_SNAPSHOT_ROOT279_V6"
    request["request_id"] = "f1-s2-root279-pair-native-observer-root310-v6-source"
    request["case_id"] = "F1_S2_DP020_ROOT279_PAIR_NATIVE_OBSERVER_ROOT310_V6"
    request["manifest"] = {
        "path": str(manifest_path),
        "sha256": "PARENT_REBINDS_AFTER_WRITING_THIS_MANIFEST",
        "bytes": "PARENT_REBINDS_AFTER_WRITING_THIS_MANIFEST",
        "payload_read_by_builder": False,
    }
    request["command"] = [
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        str(ref / "stage2_f1_s2_root279_pair_native_observer_guarded_v1.py"),
        "--run",
        "--manifest",
        str(manifest_path),
        "--attempt-root",
        "{attempt_root}",
        "--output",
        "{attempt_root}/observer/f1_s2_root279_root310_native_observer_v6.json",
        "--v1-worker",
        str(ref / "stage2_f1_native_selected_observer_v1.py"),
        "--python",
        "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python",
        "--cwd",
        str(primary_root),
        "--max-scratch-bytes",
        "268435456",
        "--max-log-bytes",
        "1048576",
        "--timeout-seconds",
        "1800",
    ]
    request["input_files"] = list(dict.fromkeys(request["input_files"] + [
        str(root310_proof_path),
        str(report_path),
        str(root310_request_path),
    ]))
    old_manifest_string = str(old_manifest_path)
    request["input_files"] = [
        str(manifest_path) if x == old_manifest_string else x
        for x in request["input_files"]
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    # The manifest does not contain its request SHA, so it can be written and
    # hashed before the request is assembled.  This avoids a cyclic input
    # closure and gives the parent an exact stable-manifest edge.
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # The request is source-prepared but its static metadata closure still
    # needs exact file-byte SHA records.  Replace the old manifest edge and
    # add the ROOT310 proof/report/request edges; the ten Part files stay
    # deferred and never enter input_files.
    input_records = dict(request.get("input_records", {}))
    input_sha256 = dict(request.get("input_sha256", {}))
    input_records.pop(old_manifest_string, None)
    input_sha256.pop(old_manifest_string, None)
    manifest_source_record = source_record(manifest_path)
    request["manifest"] = {
        "path": str(manifest_path),
        "sha256": manifest_source_record["sha256"],
        "bytes": manifest_source_record["stat_after"]["bytes"],
        "stat": manifest_source_record["stat_after"],
        "payload_read_by_builder": True,
    }
    input_records[str(manifest_path)] = {
        **manifest_source_record,
        "label": "ROOT279 V6 stable manifest",
        "payload_read_by_builder": True,
    }
    input_sha256[str(manifest_path)] = manifest_source_record["sha256"]
    for label, path, rec in [
        ("ROOT310 terminal proof", root310_proof_path, root310_proof_record),
        ("ROOT310 source snapshot report", report_path, report_record),
        ("ROOT310 source snapshot request", root310_request_path, root310_request_record),
    ]:
        input_records[str(path)] = {**rec, "label": label, "payload_read_by_builder": True}
        input_sha256[str(path)] = rec["sha256"]
    request["input_records"] = input_records
    request["input_sha256"] = input_sha256
    request["deferred_input_records"] = list(native_records.values())
    request["estimated_native_read_bytes"] = report["selected_native_total_bytes"] * 4
    request["estimated_native_read_passes"] = 4
    request["estimated_native_read_bytes_scope"] = "ROOT310 ten selected Part files, prehash+decode+posthash+decoder input; parent measures actual"
    request["execution_allowed"] = False
    request["launch_disabled"] = True
    request["native_payload_read"] = False
    request["ledger_mutation"] = False
    request["scientific_qualification"] = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    package = {
        "schema": SCHEMA,
        "status": "SOURCE_ONLY_ROOT279_ROOT310_BOUND_WAITING_PARENT",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path), "stat": stat_record(manifest_path)},
        "request": {"path": str(request_path), "sha256": sha256(request_path), "stat": stat_record(request_path)},
        "root310_proof": root310_proof_record,
        "root310_request": root310_request_record,
        "root310_report": report_record,
        "root277_proof": proof_records["same"],
        "root278_proof": proof_records["half"],
        "selected_file_count": 10,
        "selected_native_total_bytes": report["selected_native_total_bytes"],
        "estimated_native_read_bytes": report["selected_native_total_bytes"] * 4,
        "native_payload_read_by_packager": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "fresh_gate": [
            "actual ROOT310 proof/report/request SHA and exact case set",
            "all ten selected native paths/known SHA/stat are parent pre/post checked",
            "wrapper manifest path is stable before request hash",
            "ROOT277/278 proof/request/receipt identity remains exact",
            "no V5 tiny receipt or old temporary manifest is accepted",
        ],
    }
    package_path = output_dir / "source-package.json"
    package_path.write_text(json.dumps(package, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return package


def _self_test() -> None:
    # Only check the immutable policy; no production path is opened here.
    assert PROOF_SHA["root310"] == "14ac610d5c87e2aabe0c65bdadefe9a17530ff3dc0719245def0408b58701c23"
    assert 57358780 * 4 == 229435120
    assert "PARENT_AFTER_RESERVATION_REQUIRED" not in "ROOT310 source report is already a parent snapshot"
    print("stage2_f1_s2_root279_source_package_v1: self-test PASS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--primary-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.self_test:
        _self_test()
        return 0
    if not args.primary_root or not args.output_dir:
        parser.error("generation requires --primary-root and --output-dir")
    package = build_package(args.primary_root.absolute(), args.output_dir)
    print(json.dumps({"status": package["status"], "manifest": package["manifest"], "request": package["request"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
