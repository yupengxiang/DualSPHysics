from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lagrangian-fluid-lab" / "scripts" / \
    "ds_data02_stage2_f2_canonical_pipeline_v4.py"
SPEC = importlib.util.spec_from_file_location("canonical_pipeline_v4_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _plan(path: Path, *, case_id: str | None = None) -> Path:
    path.write_text(json.dumps({
        "schema": MODULE.V3.PLAN_SCHEMA,
        "selection": {
            "current_index": 65,
            "physical_case_id": case_id or MODULE.CANONICAL_ID,
            "historical_alias_rejected": MODULE.HISTORICAL_ALIAS_ID,
        },
        "current_binding": {"sha256": MODULE.CURRENT_SHA},
        "raw_binding": {"expected_raw_tree_sha256": MODULE.PENDING},
        "request_overlay": {
            "no_original_path_fallback": True,
            "request": {
                "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2",
                "source_hashes_preverified_by_parent": False,
            },
        },
    }), encoding="utf-8")
    return path


def _build_contract(tmp_path: Path) -> Path:
    plan = _plan(tmp_path / "row65-plan.json")
    contract = tmp_path / "row65-contract-v4.json"
    result = MODULE.build_contract(plan_path=plan, repo_root=ROOT,
                                   output_path=contract)
    assert result["raw_payload_read"] is False
    assert MODULE.validate_contract(contract)["stage_count"] == 7
    return contract


def _binding(contract: dict, namespace: Path, tmp_path: Path) -> Path:
    value = {"schema": MODULE.TARGET_BINDING_SCHEMA, "modules": [], "stages": []}
    for section in ("modules", "stages"):
        for item in contract[section]:
            target = namespace / item["target_relative_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item["source_path_provenance"], target)
            value[section].append({
                "role": item["role"],
                "target_path": str(target),
                "source_sha256": item["source_sha256"],
                "content_verified_after_reservation": True,
            })
    path = tmp_path / "row65-target-binding.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_v4_emits_concrete_parent_request_for_all_real_stage_interfaces(tmp_path: Path) -> None:
    contract_path = _build_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    namespace = tmp_path / "copied-bundle"
    binding_path = _binding(contract, namespace, tmp_path)
    output = namespace / "metadata" / "row65-attempt-001-request.json"
    fresh = namespace / "attempt-001"

    result = MODULE.bind_request(contract_path=contract_path, binding_path=binding_path,
                                 namespace_root=namespace, fresh_output_root=fresh,
                                 output_path=output, attempt_id="attempt-001")
    assert result["raw_payload_read"] is False
    checked = MODULE.validate_bound(output)
    assert checked["status"] == "VALIDATED_V4_CONCRETE_PARENT_REQUEST"

    request = json.loads(output.read_text(encoding="utf-8"))
    commands = {item["stage"]: item for item in request["execution"]["commands"]}
    assert set(commands) == set(MODULE.STAGE_ORDER)
    assert "--output" in commands["portable_scorer"]["argv"]
    assert all(not (isinstance(value, str) and value.startswith("<"))
               for command in commands.values()
               for value in command.get("argv", []))
    assert request["case_identity"]["current_index"] == 65
    assert request["case_identity"]["physical_case_id"] == MODULE.CANONICAL_ID
    assert request["parent_request"]["reservation_required_before_payload"] is True
    assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert request["execution"]["product_roots"]["typed"].startswith(str(fresh))


def test_v4_rejects_row78_alias_before_copy_request(tmp_path: Path) -> None:
    with pytest.raises(MODULE.V3.PipelineError):
        MODULE.build_contract(plan_path=_plan(tmp_path / "alias-plan.json",
                                              case_id=MODULE.HISTORICAL_ALIAS_ID),
                              repo_root=ROOT,
                              output_path=tmp_path / "must-not-exist.json")


def test_v4_requires_scorer_output_flag_in_contract(tmp_path: Path) -> None:
    contract = _build_contract(tmp_path)
    value = json.loads(contract.read_text(encoding="utf-8"))
    scorer = next(item for item in value["execution"]["commands"]
                  if item["stage"] == "portable_scorer")
    scorer["argv_template"].remove("--output")
    value["sha256"] = MODULE._canonical_sha(value)
    broken = tmp_path / "broken-contract.json"
    broken.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MODULE.PipelineV4Error, match="output flag"):
        MODULE.validate_contract(broken)


def test_v4_reader_bootstrap_imports_copied_v15_and_v14_only(tmp_path: Path) -> None:
    contract_path = _build_contract(tmp_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    namespace = tmp_path / "copied-bundle"
    binding_path = _binding(contract, namespace, tmp_path)
    output = namespace / "metadata" / "row65-attempt-002-request.json"
    MODULE.bind_request(contract_path=contract_path, binding_path=binding_path,
                        namespace_root=namespace, fresh_output_root=namespace / "attempt-002",
                        output_path=output, attempt_id="attempt-002")
    request = json.loads(output.read_text(encoding="utf-8"))
    reader = next(item for item in request["execution"]["commands"]
                  if item["stage"] == "reader")
    completed = subprocess.run(reader["argv"], check=False, text=True,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_v4_cli_stage_interfaces_accept_help_without_payload(tmp_path: Path) -> None:
    contract = _build_contract(tmp_path)
    for item in json.loads(contract.read_text(encoding="utf-8"))["stages"]:
        if item["role"] == "reader":
            continue
        completed = subprocess.run(
            [MODULE.PYTHON, "-B", "-I", item["source_path_provenance"], "--help"],
            check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=30,
        )
        assert completed.returncode == 0, (item["role"], completed.stderr)
