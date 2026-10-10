"""ROOT242 V13 output-slot tests.

The end-to-end test uses the existing V11 fixture, which executes the copied
V8/V13/scorer interfaces on a tiny manufactured result.  It is interface
evidence only; no production H5, BI4, native input, ledger, or model is read.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
V13_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v13.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V13 = _load(V13_PATH, "root242_v13_output_slot_test_executor")
V13_BUILDER = _load(SCRIPT_DIR / "ds_data02_stage2_f2_root242_v13_output_slot_request.py",
                    "root242_v13_output_slot_test_builder")
V11_TEST = _load(ROOT / "tests/test_ds_data02_stage2_f2_root242_v11_dynamic_open.py",
                 "root242_v11_fixture_for_v12")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stat(path: Path) -> dict[str, int]:
    value = path.lstat()
    return {"bytes": int(value.st_size), "mode_bits": int(stat.S_IMODE(value.st_mode)),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns),
            "st_dev": int(value.st_dev), "st_ino": int(value.st_ino)}


def _canonical(value: dict) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()


def _role_digest(roles: list[dict]) -> str:
    return hashlib.sha256(json.dumps(
        roles, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode()).hexdigest()


def _prepare_marker(tmp_path: Path) -> tuple[Path, Path, Path]:
    request_path, contract_path, _old_fresh = V11_TEST._v11ize(tmp_path)
    contract = json.loads(contract_path.read_text())
    inner_role = next(item for item in contract["root242_source_binding"]["roles"]
                      if item["logical_role"] == "root200_inner_request")
    inner_path = Path(inner_role["source_path_provenance"])
    inner = json.loads(inner_path.read_text())
    old_output = tmp_path / "historical-root200-output" / "proof"
    inner.setdefault("v12_forward", {})["output_root_rebind_v14"] = {
        "schema": "ds02.stage2.f2-root200-v14-output-root-rebind.v1",
        "path": str(old_output),
        "proof_output_only": True,
        "old_v13_output_root": str(old_output.parent),
    }
    inner_path.write_text(json.dumps(inner, indent=2, sort_keys=True) + "\n")
    inner_role["source_sha256"] = _sha(inner_path)
    inner_role["source_stat_provenance"] = _stat(inner_path)
    roles = contract["root242_source_binding"]["roles"]
    roles.sort(key=lambda item: str(item["logical_role"]))
    digest = _role_digest(roles)
    binding = contract["root242_source_binding"]
    binding["selected_roles_sha256"] = digest
    binding["selected_role_count"] = len(roles)
    contract["root242_source_binding"] = binding
    contract["sha256"] = _canonical(contract)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    request = json.loads(request_path.read_text())
    fresh = tmp_path / "fresh-v12"
    request["case_id"] = "fixture-root242-v13-case"
    request["attempt_id"] = "fixture-root242-v13-attempt"
    request["storage_scope"]["external_filesystem"] = str(fresh)
    request["root213_metadata_contract"] = {
        "path": str(contract_path), "sha256": contract["sha256"]}
    request["root242_v11_source_binding"]["selected_roles_sha256"] = digest
    request["input_sha256"][str(inner_path)] = inner_role["source_sha256"]
    request["input_sha256"][str(contract_path)] = _sha(contract_path)
    request["root242_v13_source_binding"] = {
        "schema": "ds02.stage2.f2-root242-v13-output-slot-source-binding.v1",
        "path": str(V13_PATH), "sha256": _sha(V13_PATH),
        "role": "v12_executor", "source_fallback": "REJECT",
    }
    request["root242_v13_output_slot"] = {
        "schema": "ds02.stage2.f2-root242-v13-output-slot.v1",
        "target_relative_path": "products",
        "replacement_pointer": "/v12_forward/output_root_rebind_v14/path",
        "old_source_path": str(old_output),
        "old_path_role": "HISTORICAL_PROVENANCE_ONLY",
        "proof_output_only": True, "attempt_owned": True,
        "original_path_fallback": "REJECT",
    }
    contract["root242_v13_output_slot"] = request["root242_v13_output_slot"]
    # The base V11 contract is immutable in production; this fixture only
    # creates a fresh isolated copy, so bind its additive slot there too.
    contract["sha256"] = _canonical(contract)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n")
    request["root213_metadata_contract"]["sha256"] = contract["sha256"]
    request["input_sha256"][str(contract_path)] = _sha(contract_path)
    request["sha256"] = _canonical(request)
    request_path.write_text(json.dumps(request, indent=2, sort_keys=True) + "\n")
    return request_path, contract_path, fresh


def test_v12_maps_only_output_marker_to_attempt_products(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    assert V13._directory_rebind_v13(("v12_forward", "output_root_rebind_v14"), root) == root / "products"
    assert V13._directory_rebind_v13(("unknown_nested_marker",), root) is None



def test_v13_requires_exact_unique_nested_marker() -> None:
    assert V13._find_output_marker_v13({
        "v12_forward": {"output_root_rebind_v14": {"path": "/old"}}
    }) == ("/v12_forward/output_root_rebind_v14/path", "/old")
    with pytest.raises(V13.Root242V13ExecutorError, match="outside exact"):
        V13._find_output_marker_v13({
            "nested": {"output_root_rebind_v14": {"path": "/old"}}
        })
    with pytest.raises(V13.Root242V13ExecutorError, match="outside exact"):
        V13._find_output_marker_v13({
            "v12_forward": {"output_root_rebind_v14": {"path": "/a"}},
            "other": {"output_root_rebind_v14": {"path": "/b"}},
        })

def test_v12_real_nested_v8_v12_scorer_fixture_rebinds_output_slot(tmp_path: Path) -> None:
    request, contract, fresh = _prepare_marker(tmp_path)
    # The actual V13 process is launched as a child, so V11's parent-PID and
    # pdeath checks exercise the same boundary as a root-managed launch.
    code = (
        "import importlib.util,os,sys;"
        "s=importlib.util.spec_from_file_location('v12child',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m.run(request=sys.argv[2],output_root=sys.argv[3],parent_pid=int(sys.argv[4]),max_wall_seconds=30)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(V13_PATH), str(request), str(fresh), str(os.getpid())],
        text=True, capture_output=True, timeout=45,
    )
    assert completed.returncode == 0, completed.stderr
    slot_report = fresh / "reports/root242-v13-output-slot-report.json"
    assert slot_report.is_file()
    value = json.loads(slot_report.read_text())
    assert value["status"] == "COMPLETE_ROOT242_V13_OUTPUT_SLOT_REBOUND"
    assert value["output_slot"]["target_relative_path"] == "products"
    assert value["output_slot"]["old_path_role"] == "HISTORICAL_PROVENANCE_ONLY"
    assert value["execution"]["original_path_fallback"] == "REJECT"
    assert value["execution"]["payload_read"] is False
    generated = fresh / "requests/root200-v11-rebased-inner.json"
    assert generated.is_file()
    rebased = json.loads(generated.read_text())
    assert rebased["v12_forward"]["output_root_rebind_v14"]["path"] == str(fresh / "products")
    # The old root is retained only in the explicit old_v13 provenance field;
    # the actionable marker path itself is target-local.
    assert rebased["v12_forward"]["output_root_rebind_v14"]["old_v13_output_root"] == str(tmp_path / "historical-root200-output")
    child = json.loads((fresh / "reports/v2-worker-report.json").read_text())
    assert child["status"] == "PASS_RELOCATED_V8_V12_TYPED_SCORER"
    assert child["execution"]["model_invoked"] is False


def test_v12_rejects_marker_with_changed_old_provenance(tmp_path: Path) -> None:
    request, contract, fresh = _prepare_marker(tmp_path)
    value = json.loads(request.read_text())
    value["root242_v13_output_slot"]["old_source_path"] = str(tmp_path / "other-old")
    value["sha256"] = _canonical(value)
    request.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    with pytest.raises(V13.Root242V13ExecutorError, match="provenance"):
        outer, inner, _ = V13.V11._outer(request)
        V13._validate_v13_binding(outer, inner, request, fresh)


def test_v12_builder_clones_v11_pair_and_rebinds_fresh_case(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    source_request, source_contract, _ = _prepare_marker(source_root)
    output_contract = tmp_path / "built/contract.json"
    output_request = tmp_path / "built/request.json"
    fresh = tmp_path / "built/fresh"
    result = V13_BUILDER.build_request(
        source_contract=source_contract, source_request=source_request,
        output_contract=output_contract, output_request=output_request,
        fresh_root=fresh, home_receipt=tmp_path / "built/home/receipt.json",
        case_id="ROOT242_V13_OUTPUT_SLOT_CASE",
        attempt_id="root-forward-242-v12-output-slot-002",
        primary_scripts_root=ROOT.parent,
    )
    assert result["status"] == "READY_FOR_PARENT_STAGE2_GUARD_V13_OUTPUT_SLOT"
    value = json.loads(output_request.read_text())
    assert value["case_id"] == "ROOT242_V13_OUTPUT_SLOT_CASE"
    assert value["attempt_id"] == "root-forward-242-v12-output-slot-002"
    assert value["storage_scope"]["external_filesystem"] == str(fresh)
    assert value["root242_v13_output_slot"]["target_relative_path"] == "products"
    assert V13_BUILDER.validate_request(
        request=output_request, contract=output_contract
    )["status"] == "ROOT242_V13_METADATA_VALIDATED_READY_FOR_PARENT"
    assert json.loads(source_request.read_text())["case_id"] == "fixture-root242-v13-case"
