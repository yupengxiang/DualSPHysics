from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).with_name("ds_data02_stage2_historical118_source_inventory_v1.py")
SPEC = importlib.util.spec_from_file_location("historical118_inventory", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: bytes = b"metadata") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _fixture(tmp_path: Path) -> dict[str, Path | str]:
    source = tmp_path / "source"
    current_rows: list[dict] = []
    evidence: list[dict] = []
    target_specs = [("F2", 48), ("F4", 22), ("F6", 48)]
    all_specs = target_specs + [("F1", 50), ("F3", 50), ("F5", 50), ("F7", 68)]
    case_number = 0
    target_ids: list[tuple[str, str]] = []
    for family, count in all_specs:
        for ordinal in range(count):
            case_number += 1
            case_id = f"{family}_CASE_{ordinal:03d}"
            base = source / family / case_id
            solver = base / "solver_attempt" / "solver_output"
            raw = solver / "data"
            for name, content in (
                ("manifest.json", b"{}"),
                ("case.xmf", b"<XMF/>"),
                ("conversion-report.json", b"{\"typed\":true}"),
                ("generated.xml", b"<case/>"),
                ("gencase-receipt.json", b"{}"),
                ("owner.json", b"{}"),
                ("solver-receipt.json", b"{}"),
                ("Run.out", b"Run metadata only\n"),
                ("RunPARTs.csv", b"Part;TimeStep [s];NpOut;NpOutPos;NpOutRho;NpOutMov\n0;0;0;0;0;0\n"),
                ("Run.csv", b"step,time\n0,0\n"),
            ):
                target = solver / name if name in {"Run.out", "RunPARTs.csv", "Run.csv"} else base / name
                _write(target, content)
            trajectory = _write(base / "trajectory.h5", b"opaque-invalid-h5-placeholder")
            _write(raw / "PartOut_000.obi4", b"opaque-native-placeholder")
            _write(raw / "Part_0000.bi4", b"opaque-native-frame-placeholder")
            _write(raw / "Part_0001.bi4", b"opaque-native-frame-placeholder")
            solver_receipt = base / "solver-receipt.json"
            generated = base / "generated.xml"
            gencase = base / "gencase-receipt.json"
            owner = base / "owner.json"
            manifest = base / "manifest.json"
            xmf = base / "case.xmf"
            conversion = base / "conversion-report.json"
            row = {
                "family_id": family,
                "physical_case_id": case_id,
                "runtime_case_alias": f"alias-{case_id}",
                "frames": 2,
                "particles": 3,
                "actual_time_window_s": [0.0, 1.0],
                "manifest": {"path": str(manifest), "recomputed_sha256": _sha(manifest)},
                "xmf": {"path": str(xmf), "recomputed_sha256": _sha(xmf)},
                "trajectory": {
                    "path": str(trajectory),
                    "producer_declared_sha256": "a" * 64,
                    "recomputed_sha256": None,
                    "bytes": trajectory.stat().st_size,
                    "mtime_ns": trajectory.stat().st_mtime_ns,
                },
                "conversion_report": {"path": str(conversion), "recomputed_sha256": _sha(conversion)},
                "source_bindings": {
                    "generated_xml": {"path": str(generated), "sha256": _sha(generated)},
                    "gencase_receipt": {"path": str(gencase), "sha256": _sha(gencase)},
                    "solver_receipt": {"path": str(solver_receipt), "sha256": _sha(solver_receipt)},
                    "owner_metadata": {"path": str(owner), "sha256": _sha(owner)},
                },
                "raw_root": {"path": str(raw), "accessible": True},
                "header": {"identity_key": "(Zone,Idp)"},
            }
            current_rows.append(row)
            if family in {"F2", "F4", "F6"}:
                target_ids.append((family, case_id))
                report = _write(base / "prior-native-evidence.json", b"prior report; no count semantics")
                evidence.append({
                    "family_id": family,
                    "physical_case_id": case_id,
                    "scope": "synthetic prior source-bound native evidence",
                    "report": {"path": str(report), "sha256": _sha(report), "bytes": report.stat().st_size},
                })
    current = source / "CURRENT336.json"
    current_doc = {
        "schema": "ds02.stage2.current336.v1",
        "cases": current_rows,
    }
    current.write_text(json.dumps(current_doc), encoding="utf-8")

    membership_index = _write(source / "membership-index.json", b"opaque prior membership index")
    union = source / "historical-union.json"
    union_doc = {
        "schema": "ds02.stage2.historical118-native-coverage-union.v3",
        "status": "PASS_EXACT_118_OF118_SOURCE_CASE_UNION",
        "historical_membership_index": {"path": str(membership_index), "sha256": "b" * 64},
        "native_evidence": evidence,
    }
    union.write_text(json.dumps(union_doc), encoding="utf-8")
    audit = source / "historical-audit.json"
    audit_doc = {
        "schema": "ds02.stage2.historical-omission-index-independent-verification.v1",
        "status": "PASS_SCOPED_EXACT_REGISTRY_AND_EVIDENCE_CLOSURE",
        "CURRENT": {"path": str(source / "historical-CURRENT-alias.json"), "sha256": _sha(current)},
        "exact_historical118_membership_verified": True,
    }
    _write(source / "historical-CURRENT-alias.json", b"alias bytes not opened")
    audit.write_text(json.dumps(audit_doc), encoding="utf-8")
    proof = _write(source / "root192-proof.json", b"proof metadata not opened")
    summary = _write(source / "root192-summary.json", b"summary metadata not opened")
    return {
        "current": current,
        "union": union,
        "audit": audit,
        "proof": proof,
        "summary": summary,
        "current_sha": _sha(current),
        "union_sha": _sha(union),
        "audit_sha": _sha(audit),
        "proof_sha": "c" * 64,
        "summary_sha": "d" * 64,
        "target_ids": target_ids,
    }


def _build(fixture: dict, output: Path) -> dict:
    result = MODULE.build_inventory(
        current_path=fixture["current"],
        current_sha256=fixture["current_sha"],
        union_path=fixture["union"],
        union_sha256=fixture["union_sha"],
        audit_path=fixture["audit"],
        audit_sha256=fixture["audit_sha"],
        root192_case_id="F2_CASE_000",
        root192_proof=fixture["proof"],
        root192_proof_sha256=fixture["proof_sha"],
        root192_summary=fixture["summary"],
        root192_summary_sha256=fixture["summary_sha"],
    )
    output.write_text(json.dumps(result), encoding="utf-8")
    return result


def test_exact_scope_stat_only_and_root192_separation(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    result = _build(fixture, tmp_path / "inventory.json")
    assert result["scope"] == {
        "historical_case_count": 118,
        "family_counts": {"F2": 48, "F4": 22, "F6": 48},
        "source_population": "historical F2/F4/F6 omission registry only",
        "f3_fine512_included": False,
        "root192_typed_particle_records_added_as_cases": False,
    }
    assert len(result["rows"]) == 118
    pilot = result["root192_typed_pilot"]
    assert pilot["status"] == "READY_SEPARATE_GUARDED_COMPARISON"
    assert pilot["typed_records_not_added_to_historical_case_count"] is True
    row = next(item for item in result["rows"] if item["physical_case_id"] == "F2_CASE_000")
    typed_h5 = row["source_artifacts"]["artifacts"]["typed_trajectory_h5"]
    assert typed_h5["content_opened_by_inventory"] is False
    assert typed_h5["declared_sha256"] == "a" * 64
    assert row["source_artifacts"]["artifacts"]["native_part_directory_stat_index"]["entry_counts"]["part_frame_bi4"] == 2
    assert row["original_omission_evidence"]["cause_inferred_from_counts"] is False
    assert row["cause_and_fate_scope"]["physical_fate"] == "UNKNOWN"
    assert len(result["next_cause_audit_source_contract"]["groups"]) == 15
    assert all(group["case_count"] <= 8 for group in result["next_cause_audit_source_contract"]["groups"])


def test_membership_rejects_f3_and_duplicates(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    union_doc = json.loads(Path(fixture["union"]).read_text())
    union_doc["native_evidence"][0]["family_id"] = "F3"
    bad = tmp_path / "bad-union.json"
    bad.write_text(json.dumps(union_doc), encoding="utf-8")
    with pytest.raises(MODULE.InventoryError, match="non-F2/F4/F6"):
        MODULE.build_inventory(
            current_path=fixture["current"], current_sha256=fixture["current_sha"],
            union_path=bad, union_sha256=_sha(bad), audit_path=fixture["audit"],
            audit_sha256=fixture["audit_sha"], root192_case_id="F2_CASE_000",
            root192_proof=None, root192_proof_sha256=None,
            root192_summary=None, root192_summary_sha256=None,
        )
    union_doc = json.loads(Path(fixture["union"]).read_text())
    union_doc["native_evidence"].append(dict(union_doc["native_evidence"][0]))
    bad.write_text(json.dumps(union_doc), encoding="utf-8")
    with pytest.raises(MODULE.InventoryError, match="exactly 118"):
        MODULE.build_inventory(
            current_path=fixture["current"], current_sha256=fixture["current_sha"],
            union_path=bad, union_sha256=_sha(bad), audit_path=fixture["audit"],
            audit_sha256=fixture["audit_sha"], root192_case_id="F2_CASE_000",
            root192_proof=None, root192_proof_sha256=None,
            root192_summary=None, root192_summary_sha256=None,
        )


def test_missing_report_is_explicit_unknown_not_count_cause(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    union_doc = json.loads(Path(fixture["union"]).read_text())
    missing = Path(union_doc["native_evidence"][0]["report"]["path"])
    missing.unlink()
    result = _build(fixture, tmp_path / "inventory.json")
    row = next(item for item in result["rows"] if item["physical_case_id"] == "F2_CASE_000")
    evidence = row["original_omission_evidence"]
    assert evidence["status"] == "REFERENCE_MISSING_PRIOR_NATIVE_EVIDENCE"
    assert evidence["cause_scope"] == "UNKNOWN_MISSING_NATIVE_EVIDENCE"
    assert evidence["cause_inferred_from_counts"] is False
    assert evidence["physical_fate"] == "UNKNOWN"


def test_cli_is_bounded_metadata_only(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    output = tmp_path / "cli-output.json"
    command = [
        sys.executable, str(SCRIPT),
        "--current", str(fixture["current"]), "--current-sha256", fixture["current_sha"],
        "--membership-evidence", str(fixture["union"]), "--membership-sha256", fixture["union_sha"],
        "--audit-evidence", str(fixture["audit"]), "--audit-sha256", fixture["audit_sha"],
        "--root192-case-id", "F2_CASE_000",
        "--root192-proof", str(fixture["proof"]), "--root192-proof-sha256", fixture["proof_sha"],
        "--root192-summary", str(fixture["summary"]), "--root192-summary-sha256", fixture["summary_sha"],
        "--output", str(output),
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    assert '"h5_opened": false' in completed.stdout
    assert json.loads(output.read_text())["scope"]["historical_case_count"] == 118
