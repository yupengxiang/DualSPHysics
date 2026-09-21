from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
SCRIPT = LAB / "scripts/f7_pump_root_review_contract_v2.py"
SPEC = importlib.util.spec_from_file_location("f7_root_review_contract_v2", SCRIPT)
assert SPEC and SPEC.loader
CONTRACT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CONTRACT)


def _copy_reference_tree(destination: Path) -> None:
    for spec in CONTRACT.ROUTE_RECEIPTS.values():
        source = LAB / spec["path"]
        target = destination / spec["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for spec in CONTRACT.PUMP_SOURCES.values():
        source = LAB / spec["path"]
        target = destination / spec["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_workspace_is_bound_but_remains_root_review_only_blocked() -> None:
    value = CONTRACT.build_contract(LAB)

    assert value["schema"] == "core.f7.pump_recirculation.root_review_contract.v2"
    assert value["status"] == "root_review_only_blocked"
    assert value["mode"] == "diagnostic_only"
    assert value["diagnostic_only"] is True
    assert value["root_review_only"] is True
    assert value["fail_closed"] is True

    integrity = value["reference_integrity"]
    assert integrity["route_closure_receipts_bound"] is True
    assert integrity["official_pump_sources_bound"] is True
    assert integrity["all_hash_and_semantic_checks_pass"] is True
    for binding in (
        *integrity["route_closure_receipts"].values(),
        *integrity["official_pump_sources"].values(),
    ):
        assert binding["exists"] is True
        assert binding["hash_match"] is True
        assert binding["usable"] is True
        assert binding["observed_sha256"] == binding["expected_sha256"]


def test_contract_freezes_unresolved_gates_and_zero_authorization() -> None:
    value = CONTRACT.verify(LAB)

    motion = value["motion_contract"]
    assert motion["piecewise_segments"] == {
        "declared_from_official_xml": True,
        "evaluation_status": "sampled",
        "runtime_verified": False,
    }
    assert motion["finish_velocity"] == {
        "status": "sampled_uncertified",
        "sampled": True,
        "certified": False,
        "runtime_verified": False,
    }

    denominator = value["proposal_denominator"]
    assert denominator["planned_rows"] == 15
    assert denominator["executed"] == 0
    assert denominator["credit"] == 0
    assert denominator["unattempted"] == 15

    assert all(
        item["frozen"] is False for item in value["material_regions"].values()
    )
    assert all(
        item["present"] is False
        for item in value["causal_runtime_contract"].values()
    )
    assert value["permissions"] == {
        "definition": False,
        "gencase": False,
        "native": False,
        "solver": False,
        "GPU": False,
        "queue": 0,
        "registry": 0,
        "ledger": 0,
    }
    assert value["qualification"] == {
        "claim": "none",
        "credit": 0,
        "T1": False,
        "T2": False,
        "admission": False,
    }
    assert "finish_velocity_is_sampled_and_uncertified" in value["blockers"]
    assert "trajectory_producer_missing" in value["blockers"]


def test_route_receipt_hash_mismatch_fails_closed_without_opening_permissions(
    tmp_path: Path,
) -> None:
    _copy_reference_tree(tmp_path)
    route = tmp_path / CONTRACT.ROUTE_RECEIPTS["F5"]["path"]
    route.write_bytes(route.read_bytes() + b"\n")

    value = CONTRACT.build_contract(tmp_path)
    binding = value["reference_integrity"]["route_closure_receipts"]["F5"]
    assert binding["exists"] is True
    assert binding["hash_match"] is False
    assert binding["usable"] is False
    assert value["reference_integrity"]["route_closure_receipts_bound"] is False
    assert "route_receipt_hash_mismatch:F5" in value["blockers"]
    assert value["status"] == "root_review_only_blocked"
    assert value["permissions"]["solver"] is False
    assert value["permissions"]["GPU"] is False
    assert value["permissions"]["queue"] == 0
    assert value["qualification"]["credit"] == 0


def test_missing_official_source_fails_closed(tmp_path: Path) -> None:
    _copy_reference_tree(tmp_path)
    missing = tmp_path / CONTRACT.PUMP_SOURCES["moving"]["path"]
    missing.unlink()

    value = CONTRACT.build_contract(tmp_path)
    binding = value["reference_integrity"]["official_pump_sources"]["moving"]
    assert binding["exists"] is False
    assert binding["hash_match"] is False
    assert binding["usable"] is False
    assert value["reference_integrity"]["official_pump_sources_bound"] is False
    assert "official_pump_source_missing:moving" in value["blockers"]
    assert value["qualification"]["admission"] is False


def test_contract_is_read_only_and_has_no_runtime_writer_entry_point() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "Popen(" not in source
    assert "write_text(" not in source
    assert "write_bytes(" not in source
    assert "open(\"w\"" not in source
    assert "solver_binary" not in source
    assert "queue_submit" not in source


def test_cli_emits_json_without_creating_an_output_artifact(capsys) -> None:
    assert CONTRACT.main(["--root", str(LAB)]) == 0
    output = capsys.readouterr().out
    value = json.loads(output)
    assert value["status"] == "root_review_only_blocked"
    assert value["diagnostic_only"] is True
