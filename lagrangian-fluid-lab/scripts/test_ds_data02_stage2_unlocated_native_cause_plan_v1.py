from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_unlocated_native_cause_plan_v1.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(SCRIPT), *args], text=True, capture_output=True, check=False)


def _write_fixture(tmp_path: Path, *, typed_case: str | None = None, duplicate: bool = False) -> dict[str, Path]:
    cases = ["F4_CASE_A", "F4_CASE_B"]
    rows = []
    native_evidence = []
    for index, case in enumerate(cases):
        if duplicate and index == 1:
            case = cases[0]
        report = tmp_path / f"{case}-native.json"
        h5 = tmp_path / f"{case}.h5"
        native_dir = tmp_path / f"{case}-native-dir"
        rows.append(
            {
                "physical_case_id": case,
                "family_id": "F4",
                "current336_index": 10 + index,
                "historical_118_membership": True,
                "identity": {
                    "current_physical_case_id": case,
                    "current_identity_match": True,
                    "current_trajectory_bytes": 1234 + index,
                    "current_trajectory_declared_sha256": f"{index + 1:064x}",
                    "current_trajectory_path": str(h5),
                },
                "cause_and_fate_scope": {
                    "typed_lifecycle": "DECLARED_H5_ONLY_NOT_OPENED",
                    "typed_h5_reference_status": "PRESENT_STAT_ONLY",
                },
                "original_omission_evidence": {
                    "status": "REFERENCE_PRESENT_PRIOR_NATIVE_EVIDENCE",
                    "report": {
                        "path": str(report),
                        "declared_sha256": f"{index + 11:064x}",
                        "status": "PRESENT_STAT_ONLY",
                        "stat": {"bytes": 12 + index},
                    },
                },
                "source_artifacts": {
                    "artifacts": {
                        "typed_trajectory_h5": {
                            "path": str(h5),
                            "known_sha256": f"{index + 1:064x}",
                            "bytes": 1234 + index,
                            "status": "PRESENT_STAT_ONLY",
                        },
                        "native_part_directory_stat_index": {
                            "path": str(native_dir),
                            "status": "PRESENT_STAT_ONLY",
                        },
                        "generated_xml": {
                            "path": str(tmp_path / f"{case}.xml"),
                            "status": "PRESENT_STAT_ONLY",
                        },
                    }
                },
            }
        )
        native_evidence.append(
            {
                "family_id": "F4",
                "physical_case_id": case,
                "report": {"path": str(report), "sha256": f"{index + 11:064x}", "bytes": 12 + index},
            }
        )
    overlay = {
        "schema": "ds02.stage2.original118-native-cause-actual-overlay.v1",
        "remaining_cause_not_located_case_ids": cases if not duplicate else [cases[0], cases[0]],
        "cause_not_located_after_completed_scan_cases": 2,
        "actual_typed_native_saved_frame_join_physical_cases": 0,
        "actual_join_proofs": [],
    }
    inventory = {
        "schema": "ds02.stage2.historical118-source-inventory.v1",
        "rows": rows,
    }
    union = {
        "schema": "ds02.stage2.historical118-native-coverage-union.v3",
        "native_evidence": native_evidence,
    }
    current = {"schema": "ds02.stage2.current336.v1", "rows": []}
    paths = {}
    for name, value in (("overlay", overlay), ("inventory", inventory), ("union", union), ("current", current)):
        path = tmp_path / f"{name}.json"
        path.write_text(json.dumps(value) + "\n", encoding="utf-8")
        paths[name] = path
    if typed_case:
        proof = {
            "schema": "ds02.stage2.root-actual-verification.v1",
            "status": "VERIFIED_ACTUAL_F4_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
            "case_verifications": [
                {
                    "physical_case_id": typed_case,
                    "family_id": "F4",
                    "status": "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY",
                    "summary": str(tmp_path / "typed-summary.json"),
                    "records_stat_only": {"path": str(tmp_path / "typed-records.jsonl"), "bytes": 10},
                    "source_trajectory": {"path": str(tmp_path / "typed.h5"), "known_sha256": "2" * 64},
                    "source_H5_prepost_known_SHA_and_current_stat_equal": True,
                    "native_cause_fate_legal_flux_dynamics": "UNKNOWN",
                }
            ],
        }
        path = tmp_path / "typed-proof.json"
        path.write_text(json.dumps(proof) + "\n", encoding="utf-8")
        paths["typed"] = path
    return paths


def _prepare(tmp_path: Path, paths: dict[str, Path]) -> tuple[subprocess.CompletedProcess[str], Path]:
    manifest = tmp_path / "out-manifest.json"
    request = tmp_path / "out-request.json"
    checkpoint = tmp_path / "out-checkpoint.json"
    args = [
        "prepare",
        "--overlay", str(paths["overlay"]),
        "--inventory", str(paths["inventory"]),
        "--union", str(paths["union"]),
        "--current", str(paths["current"]),
        "--manifest-output", str(manifest),
        "--request-output", str(request),
        "--checkpoint", str(checkpoint),
        "--allow-fixture",
    ]
    if "typed" in paths:
        args += ["--typed-proof", str(paths["typed"])]
    return _run(*args), manifest


def test_prepare_keeps_unlocated_without_completed_typed_product(tmp_path: Path) -> None:
    result, manifest = _prepare(tmp_path, _write_fixture(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(manifest.read_text(encoding="utf-8"))
    assert value["scope"]["remaining_unlocated_case_count"] == 2
    assert value["scope"]["unlocated_cases_with_completed_typed_product"] == 0
    assert value["scope"]["candidate_native_typed_join_case_count"] == 0
    assert {row["classification"] for row in value["cases"]} == {"NATIVE_SOURCE_INDEXED_TYPED_LIFECYCLE_MISSING"}
    assert all(row["native_cause_credit"] == "NONE_FROM_THIS_PLAN" for row in value["cases"])


def test_completed_typed_product_creates_only_one_exact_candidate(tmp_path: Path) -> None:
    result, manifest = _prepare(tmp_path, _write_fixture(tmp_path, typed_case="F4_CASE_A"))
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(manifest.read_text(encoding="utf-8"))
    assert value["scope"]["unlocated_typed_case_ids"] == ["F4_CASE_A"]
    assert value["scope"]["candidate_native_typed_join_case_ids"] == ["F4_CASE_A"]
    assert value["cases"][0]["classification"] == "TYPED_LIFECYCLE_READY_NATIVE_JOIN"


def test_duplicate_inventory_or_overlay_identity_is_rejected(tmp_path: Path) -> None:
    result, _ = _prepare(tmp_path, _write_fixture(tmp_path, duplicate=True))
    assert result.returncode != 0
    assert "duplicated" in result.stdout


def test_validate_rejects_payload_in_metadata_inputs(tmp_path: Path) -> None:
    result, manifest = _prepare(tmp_path, _write_fixture(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["metadata_inputs"].append({"path": "/deferred/trajectory.h5", "sha256": "3" * 64})
    manifest.write_text(json.dumps(value) + "\n", encoding="utf-8")
    checked = _run("validate", "--manifest", str(manifest))
    assert checked.returncode != 0
    assert "payload path" in checked.stdout


def test_prepare_has_real_subprocess_request_and_no_payload_input_files(tmp_path: Path) -> None:
    result, manifest = _prepare(tmp_path, _write_fixture(tmp_path))
    assert result.returncode == 0, result.stdout + result.stderr
    request = json.loads((tmp_path / "out-request.json").read_text(encoding="utf-8"))
    assert request["schema"] == "ds02.request.v1"
    assert request["launch_allowed"] is False
    assert request["command"][2] == "validate"
    assert all(Path(item["path"]).suffix not in {".h5", ".jsonl", ".bi4", ".obi4"} for item in request["input_files"])
    checked = _run("validate", "--manifest", str(manifest))
    assert checked.returncode == 0, checked.stdout + checked.stderr

