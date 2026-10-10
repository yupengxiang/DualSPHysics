from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "lagrangian-fluid-lab" / "scripts" / "ds_data02_stage2_f2_canonical_pipeline_v3.py"


def _module():
    spec = importlib.util.spec_from_file_location("canonical_pipeline_v3", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _plan(path: Path, module) -> Path:
    value = {
        "schema": module.PLAN_SCHEMA,
        "selection": {
            "current_index": 65,
            "physical_case_id": module.CANONICAL_ID,
            "historical_alias_rejected": module.HISTORICAL_ALIAS_ID,
        },
        "current_binding": {"sha256": module.CURRENT_SHA},
        "raw_binding": {"expected_raw_tree_sha256": module.PENDING_RAW_SHA},
        "request_overlay": {
            "no_original_path_fallback": True,
            "request": {
                "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2",
                "source_hashes_preverified_by_parent": False,
            },
        },
    }
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_build_and_validate_binds_actual_loader_and_cli_subcommands(tmp_path: Path):
    module = _module()
    plan = _plan(tmp_path / "plan.json", module)
    contract_path = tmp_path / "contract.json"

    result = module.build_contract(plan_path=plan, repo_root=ROOT, output_path=contract_path)
    assert result["raw_payload_read"] is False
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    assert contract["schema"] == module.SCHEMA
    assert contract["stage_abi"]["restorer"]["filename"] == \
        "ds_data02_stage2_f2_native_raw_to_label_loader_v1.py"
    assert contract["stage_abi"]["restorer"]["argv_tail"][0] == "prepare"
    commands = {item["stage"]: item for item in contract["execution"]["commands"]}
    assert commands["worker"]["argv_template"][4] == "run"
    assert commands["label_producer"]["argv_template"][4] == "run"
    assert commands["reader"]["invocation"] == "python_import_entrypoint"
    assert module.validate_contract(contract_path)["status"].startswith("VALIDATED_")


def test_bind_checks_copied_code_sha_and_rejects_changed_binding(tmp_path: Path):
    module = _module()
    plan = _plan(tmp_path / "plan.json", module)
    contract_path = tmp_path / "contract.json"
    module.build_contract(plan_path=plan, repo_root=ROOT, output_path=contract_path)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    namespace = tmp_path / "bundle"
    binding = {"schema": module.TARGET_BINDING_SCHEMA, "modules": [], "stages": []}
    for section in ("modules", "stages"):
        for item in contract[section]:
            target = namespace / item["target_relative_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(item["source_path_provenance"], target)
            binding[section].append({
                "role": item["role"], "target_path": str(target),
                "source_sha256": item["source_sha256"],
                "content_verified_after_reservation": True,
            })
    binding_path = tmp_path / "binding.json"
    binding_path.write_text(json.dumps(binding), encoding="utf-8")
    request_path = tmp_path / "request.json"
    result = module.bind_contract(contract_path=contract_path, binding_path=binding_path,
                                  namespace_root=namespace, output_path=request_path,
                                  fresh_output_root=namespace / "attempt", attempt_id="tiny-001")
    assert result["raw_payload_read"] is False
    assert module.validate_bound(request_path)["status"].startswith("VALIDATED_")

    wrong = json.loads(binding_path.read_text(encoding="utf-8"))
    wrong["stages"][0]["source_sha256"] = "0" * 64
    wrong_path = tmp_path / "wrong-binding.json"
    wrong_path.write_text(json.dumps(wrong), encoding="utf-8")
    with pytest.raises(module.PipelineError):
        module.bind_contract(contract_path=contract_path, binding_path=wrong_path,
                             namespace_root=namespace, output_path=tmp_path / "bad-request.json",
                             fresh_output_root=namespace / "attempt-bad", attempt_id="tiny-002")
