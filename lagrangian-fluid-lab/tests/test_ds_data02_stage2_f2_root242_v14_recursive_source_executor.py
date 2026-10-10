"""Small real V14 recursive-copy/V8/V12/scorer interface tests.

The fixture is manufactured by the existing V11/V13 test harness.  It runs
the actual copied runtime entry, not a stub, and never opens production H5,
BI4, native, or ledger inputs.  The production ROOT242 report remains a
metadata-only source for the parent admission request.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V14_BUILDER = _load(
    SCRIPT_DIR / "ds_data02_stage2_f2_root242_v14_recursive_source_request.py",
    "root242_v14_recursive_source_test_builder",
)
V14_PREFLIGHT = _load(
    SCRIPT_DIR / "ds_data02_stage2_f2_root242_recursive_source_preflight_v14.py",
    "root242_v14_recursive_source_test_preflight",
)
V14_EXECUTOR = _load(
    SCRIPT_DIR / "ds_data02_stage2_f2_root242_portable_typed_executor_v14.py",
    "root242_v14_recursive_source_test_executor",
)
V13_BUILDER = _load(
    SCRIPT_DIR / "ds_data02_stage2_f2_root242_v13_output_slot_request.py",
    "root242_v13_builder_for_v14_recursive_source",
)
V13_TEST = _load(
    ROOT / "tests/test_ds_data02_stage2_f2_root242_v13_output_slot.py",
    "root242_v13_fixture_for_v14_recursive_source",
)


def _write_report(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8")


def _prepare_v14(tmp_path: Path) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "source"
    source_root.mkdir()
    v11_request, v11_contract, _ = V13_TEST._prepare_marker(source_root)
    source_request = source_root / "v13/source-request.json"
    source_contract = source_root / "v13/source-contract.json"
    V13_BUILDER.build_request(
        source_contract=v11_contract, source_request=v11_request,
        output_contract=source_contract, output_request=source_request,
        fresh_root=source_root / "v13/fresh",
        home_receipt=source_root / "v13/home/receipt.json",
        case_id="fixture-root242-v13-source-case",
        attempt_id="fixture-root242-v13-source-attempt",
        primary_scripts_root=ROOT.parent,
    )
    preflight = V14_PREFLIGHT.preflight_actual(
        request_path=source_request, target_root=tmp_path / "metadata-probe"
    )
    assert preflight["status"] == "READY_FOR_PARENT_GUARD_METADATA_ONLY"
    report = tmp_path / "preflight.json"
    _write_report(report, preflight)
    output_contract = tmp_path / "built/source-contract.json"
    output_request = tmp_path / "built/request.json"
    fresh = tmp_path / "built/fresh"
    result = V14_BUILDER.build_request(
        source_contract=source_contract, source_request=source_request,
        preflight_report=report, output_contract=output_contract,
        output_request=output_request, fresh_root=fresh,
        home_receipt=tmp_path / "built/home/receipt.json",
        case_id="ROOT242_V14_FIXTURE_CASE", attempt_id="root242-v14-fixture-001",
        primary_scripts_root=ROOT.parent,
    )
    assert result["status"] == "READY_FOR_PARENT_STAGE2_GUARD_V14_RECURSIVE_SOURCE_CLOSURE"
    assert result["copy_plan"]["source_fallback"] == "REJECT"
    assert result["copy_plan"]["total_role_count"] == preflight["role_count"] + 2
    return output_request, output_contract, fresh


def test_v14_real_metadata_validation_and_role_cost_split(tmp_path: Path) -> None:
    request, contract, _fresh = _prepare_v14(tmp_path)
    value = V14_EXECUTOR.validate_request(request, contract)
    assert value["status"] == "ROOT242_V14_METADATA_VALIDATED_READY_FOR_PARENT"
    outer = json.loads(request.read_text(encoding="utf-8"))
    classes = outer["v14_copy_plan"]["deferred_role_classes"]
    assert classes["policy"]["all_categories_are_copy_inputs"] is True
    assert classes["policy"]["historical_provenance_is_not_actionable"] is True
    assert outer["scope"]["original_path_fallback"] == "REJECT"


def test_v14_real_copied_runtime_rebinds_recursive_graph(tmp_path: Path) -> None:
    request, contract, fresh = _prepare_v14(tmp_path)
    code = (
        "import importlib.util,os,sys;"
        "s=importlib.util.spec_from_file_location('v14child',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m.run(request=sys.argv[2],output_root=sys.argv[3],"
        "parent_pid=int(sys.argv[4]),max_wall_seconds=45)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code, str(SCRIPT_DIR /
         "ds_data02_stage2_f2_root242_portable_typed_executor_v14.py"),
         str(request), str(fresh), str(os.getpid())],
        text=True, capture_output=True, timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    report = fresh / "reports/root242-v14-recursive-executor-report.json"
    assert report.is_file()
    value = json.loads(report.read_text(encoding="utf-8"))
    assert value["status"] == "COMPLETE_ROOT242_V14_RECURSIVE_SOURCE_CLOSURE"
    assert value["execution"]["v8_validator"] is True
    assert value["execution"]["v12_validator"] is True
    assert value["execution"]["typed_scorer"] is True
    assert value["execution"]["original_path_fallback"] == "REJECT"
    assert value["execution"]["ledger_mutated"] is False
    generated = fresh / "requests/root200-v11-rebased-inner.json"
    assert generated.is_file()
    rebased = json.loads(generated.read_text(encoding="utf-8"))
    assert rebased["v12_forward"]["output_root_rebind_v14"]["path"] == str(fresh / "products")


def test_v14_rejects_missing_recursive_preflight_role(tmp_path: Path) -> None:
    request, contract, _fresh = _prepare_v14(tmp_path)
    value = json.loads(contract.read_text(encoding="utf-8"))
    roles = value["root242_source_binding"]["roles"]
    value["root242_source_binding"]["roles"] = [
        item for item in roles if item.get("logical_role") != "v14_recursive_preflight_report"
    ]
    value["sha256"] = V14_BUILDER._canonical(value)
    contract.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # The immutable outer request still binds the old contract; V14 must fail
    # before it can copy anything rather than silently treating the report as
    # optional provenance.
    try:
        V14_EXECUTOR.validate_request(request, contract)
    except Exception as error:
        assert "contract" in str(error).lower() or "role" in str(error).lower()
    else:
        raise AssertionError("V14 accepted a contract without its sealed preflight role")
