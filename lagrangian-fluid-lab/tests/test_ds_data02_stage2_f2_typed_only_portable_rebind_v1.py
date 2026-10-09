"""Strict target-relative relocation and real copied V8 CLI tests."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_only_portable_rebind_v1.py"
SOURCE_SCRIPTS = ROOT / "scripts"


def _load():
    spec = importlib.util.spec_from_file_location("typed_only_portable_rebind_v1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _manifest(module, source_dir: Path, artifacts: list[dict], *, entry: str, request: str) -> dict:
    value = {
        "schema": module.MANIFEST_SCHEMA,
        "status": "PORTABLE_TYPED_ONLY_DEPENDENCY_AUDIT_METADATA_COMPLETE",
        "artifacts": artifacts,
        "portable_loading_entry": {
            "schema": "ds02.stage2.f2-typed-only-portable-loading-entry.v1",
            "entrypoint_logical_role": "root191_v4_entrypoint",
            "entrypoint_target_relative_path": entry,
            "request_target_relative_path": request,
            "frozen_v15_target_relative_path": "evidence/frozen-v15/request.json",
            "current_target_relative_path": "evidence/current/CURRENT.json",
            "result_target_relative_path": "products/result.json",
            "typed_h5_target_relative_path": "products/result.h5",
            "fresh_proof_target_relative_path": "evidence/proof.json",
            "operator_report_target_relative_path": "reports/operator.json",
            "runtime_sibling_directory": "runtime",
            "argv0_policy": "literal_shared_venv_only",
            "source_fallback": "REJECT",
            "no_model": True,
            "model_invoked": False,
        },
        "path_policy": {"original_absolute_path_fallback": "REJECT"},
    }
    value["sha256"] = module._canonical(value)
    return value


def _artifact(module, source: Path, role: str, target: str, *, kind: str = "runtime_source") -> dict:
    stat = module._stat(source)
    return {
        "logical_role": role,
        "source_kind": kind,
        "source_path_provenance": str(source),
        "source_sha256": module._sha(source),
        "source_sha256_basis": "manifest_read_bounded",
        "source_stat_provenance": stat,
        "source_stat_is_target_claim": False,
        "target_relative_path": target,
        "actionable": True,
        "content_read_by_manifest": True,
    }


def _stage_roles(module, contract: dict, *, only: set[str] | None = None) -> None:
    root = Path(contract["relocated_root"])
    for role in contract["roles"]:
        if only is not None and role["logical_role"] not in only:
            continue
        target = root / role["target_relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(role["source_path_provenance"], target)


def _basic_fixture(tmp_path: Path):
    module = _load()
    source = tmp_path / "original-source"
    source.mkdir()
    entry = source / "entry.py"
    request = source / "request.json"
    entry.write_text("print('fixture')\n", encoding="utf-8")
    request.write_text('{"schema":"fixture"}\n', encoding="utf-8")
    manifest = _manifest(module, source, [
        _artifact(module, entry, "root191_v4_entrypoint", "runtime/entry.py"),
        _artifact(module, request, "root191_inner_request", "evidence/request.json", kind="bounded_evidence"),
    ], entry="runtime/entry.py", request="evidence/request.json")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    root = tmp_path / "relocated"
    contract_path = tmp_path / "contract.json"
    contract = module.build_contract(manifest_path=manifest_path, relocated_root=root,
                                     output=contract_path, contract_id="fixture")
    _stage_roles(module, contract)
    return module, source, root, contract_path, contract


def test_contract_seal_uses_target_sha_and_survives_missing_provenance(tmp_path: Path):
    module, source, root, contract_path, contract = _basic_fixture(tmp_path)
    # The contract contains provenance only; the original source may be gone
    # before the relocated target is sealed.
    (source / "entry.py").unlink()
    (source / "request.json").unlink()
    sealed_path = tmp_path / "sealed.json"
    sealed = module.seal_contract(contract_path=contract_path, output=sealed_path)
    assert sealed["all_target_content_verified"] is True
    checked = module.validate_sealed(sealed_path)
    assert checked["status"] == "SEALED_RELOCATION_VALIDATED"
    assert all(item["source_inode_mtime_equivalence"] == "NOT_CLAIMED"
               for item in sealed["roles"])


def test_rebind_rejects_missing_changed_symlink_and_escape_targets(tmp_path: Path):
    module, source, root, contract_path, contract = _basic_fixture(tmp_path)
    missing_root = tmp_path / "missing-relocated"
    missing_root.mkdir()
    missing_contract_path = tmp_path / "missing-contract.json"
    module.build_contract(
        manifest_path=tmp_path / "manifest.json", relocated_root=missing_root,
        output=missing_contract_path, contract_id="missing")
    with pytest.raises(module.PortableRebindError, match="required relocated role is missing"):
        module.seal_contract(contract_path=missing_contract_path, output=tmp_path / "missing-sealed.json")

    target = root / "runtime/entry.py"
    target.write_text("changed\n", encoding="utf-8")
    with pytest.raises(module.PortableRebindError, match="content SHA differs"):
        module.seal_contract(contract_path=contract_path, output=tmp_path / "changed-sealed.json")
    target.write_text("print('fixture')\n", encoding="utf-8")

    outside = tmp_path / "outside.py"
    outside.write_text("outside\n", encoding="utf-8")
    target.unlink()
    target.symlink_to(outside)
    with pytest.raises(module.PortableRebindError, match="symlink"):
        module.seal_contract(contract_path=contract_path, output=tmp_path / "symlink-sealed.json")

    bad_manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    bad_manifest["artifacts"][0]["target_relative_path"] = "../outside.py"
    bad_manifest["sha256"] = module._canonical(bad_manifest)
    bad_path = tmp_path / "escape-manifest.json"
    bad_path.write_text(json.dumps(bad_manifest, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(module.PortableRebindError, match="not safely relative"):
        module.build_contract(manifest_path=bad_path, relocated_root=tmp_path / "other",
                             output=tmp_path / "escape-contract.json", contract_id="escape")

    absolute_manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    absolute_manifest["artifacts"][0]["target_relative_path"] = str(source / "entry.py")
    absolute_manifest["sha256"] = module._canonical(absolute_manifest)
    absolute_path = tmp_path / "absolute-manifest.json"
    absolute_path.write_text(json.dumps(absolute_manifest, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(module.PortableRebindError, match="not safely relative"):
        module.build_contract(manifest_path=absolute_path, relocated_root=tmp_path / "other2",
                             output=tmp_path / "absolute-contract.json", contract_id="absolute")


def _real_v8_fixture(tmp_path: Path):
    """Copy the actual V4/V8 sibling closure and manufacture only tiny JSON."""
    module = _load()
    v8_test_path = ROOT / "tests/test_ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
    spec = importlib.util.spec_from_file_location("v8_fixture_factory", v8_test_path)
    assert spec and spec.loader
    factory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(factory)
    fixture_base = tmp_path / "fixture-input"
    fixture_base.mkdir()
    request_path, result_path, request_value, _ = factory._fixture(fixture_base)

    original = tmp_path / "original"
    original.mkdir()
    original_result = original / "result.json"
    shutil.copyfile(result_path, original_result)
    root = tmp_path / "relocated"
    product = root / "products"
    runtime = root / "runtime"
    evidence = root / "evidence"
    product.mkdir(parents=True)
    runtime.mkdir(parents=True)
    evidence.mkdir(parents=True)

    request_value = copy.deepcopy(request_value)
    request_value["fixture_only"] = True
    request_value["result"]["path"] = str(product / "v16-result.json")
    request_value["relocation"] = {
        "target_root": str(runtime), "output_root": str(product),
        "original_roots": [str(original)],
    }
    request_value["sha256"] = factory.v8.canonical_sha(request_value)
    original_request = original / "proof-request.json"
    original_request.write_text(json.dumps(request_value, sort_keys=True) + "\n", encoding="utf-8")
    target_request = evidence / "proof-request.json"
    shutil.copyfile(original_request, target_request)
    shutil.copyfile(original_result, product / "v16-result.json")

    names = [
        "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py",
        "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v3.py",
        "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v2.py",
        "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py",
        "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py",
        "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py",
        "ds_data02_stage2_f2_fresh_v16_proof_request_v66.py",
        "ds_data02_stage2_f2_typed_only_evaluator_v1.py",
        "ds_data02_stage2_f2_no_model_evaluator_v3.py",
        "ds_data02_stage2_f2_no_model_evaluator_v2.py",
        "ds_data02_stage2_f2_replay_v14.py",
        "ds_data02_stage2_f2_replay_v15.py",
    ]
    artifacts = []
    for name in names:
        source = SOURCE_SCRIPTS / name
        role = "root191_v4_entrypoint" if name.endswith("_v4.py") else f"runtime_{name[:-3]}"
        artifacts.append(_artifact(module, source, role, f"runtime/{name}"))
    artifacts.extend([
        _artifact(module, original_request, "fixture_request", "evidence/proof-request.json", kind="bounded_evidence"),
        _artifact(module, original_result, "fixture_result", "products/v16-result.json", kind="bounded_evidence"),
    ])
    manifest = _manifest(module, original, artifacts,
                         entry="runtime/ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v4.py",
                         request="evidence/proof-request.json")
    manifest_path = tmp_path / "fixture-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    contract_path = tmp_path / "fixture-contract.json"
    contract = module.build_contract(manifest_path=manifest_path, relocated_root=root,
                                     output=contract_path, contract_id="real-v8-fixture")
    _stage_roles(module, contract)
    sealed_path = tmp_path / "fixture-sealed.json"
    module.seal_contract(contract_path=contract_path, output=sealed_path)
    return module, root, sealed_path, target_request, product


def test_real_copied_v4_cli_runs_v8_validator_without_original_runtime(tmp_path: Path):
    module, root, sealed, request, product = _real_v8_fixture(tmp_path)
    helper_target = root / "runtime" / SCRIPT.name
    shutil.copyfile(SCRIPT, helper_target)
    # The helper role is mandatory in a real contract; the copied helper is
    # added after the initial seal only for this test's explicit CLI command.
    # Rebuild/reseal with the helper source role represented by the contract.
    contract_path = tmp_path / "fixture-contract.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    helper_role = next(role for role in contract["roles"] if role["logical_role"] == "typed_only_portable_rebind_v1")
    helper_role["source_sha256"] = module._sha(SCRIPT)
    helper_role["source_stat_provenance"] = module._stat(SCRIPT)
    contract["sha256"] = module._canonical(contract)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sealed = tmp_path / "fixture-sealed-v2.json"
    module.seal_contract(contract_path=contract_path, output=sealed)
    # The copied child must be usable after every historical source-provenance
    # path disappears; this catches an implicit original-worktree fallback.
    shutil.rmtree(tmp_path / "original")
    output_relative = "reports/v8-fixture-report.json"
    result = subprocess.run([
        sys.executable, str(helper_target), "run", "--overlay", str(sealed),
        "--request-relative", "evidence/proof-request.json",
        "--output-relative", output_relative, "--entry-mode", "run-v8-fixture",
        "--python", sys.executable, "--parent-pid", str(os.getpid()),
        "--max-wall-seconds", "30",
    ], check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["status"] == "COMPLETE_RELOCATED_TYPED_ONLY_CHILD"
    report = json.loads((root / output_relative).read_text(encoding="utf-8"))
    assert report["status"] == "PASS_REAL_V8_VALIDATOR_FIXTURE_ONLY"
    assert report["execution"]["model_invoked"] is False
    assert (root / "reports/v8-fixture-report.guard-receipt.json").is_file()
