from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace331_v16_typed_event_adapter_v4.py"
SPEC = importlib.util.spec_from_file_location("namespace331_v16_typed_event_adapter_v4_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

REAL_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/lineage/"
    "v29-namespace331-v3-role-proof-root200-source-prepared-001/"
    "root200-v3-source-event-request.json"
)


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_root200_real_cli_bind_validate_convert_validate_result_chain(tmp_path: Path) -> None:
    bound = tmp_path / "root200-v4-request.json"
    admission = tmp_path / "admission.json"
    result = tmp_path / "unknown-result.json"

    bind = _run("bind-request", "--source-request", str(REAL_REQUEST), "--output", str(bound))
    assert bind.returncode == 0, bind.stderr
    validate = _run("validate-request", "--request", str(bound), "--output", str(admission))
    assert validate.returncode == 0, validate.stderr
    admission_value = json.loads(admission.read_text(encoding="utf-8"))
    assert admission_value["schema"] == MODULE.ADAPTER_SCHEMA
    assert admission_value["all_roles_known"] is False
    assert admission_value["typed_content_required"] is False

    # The path does not exist.  A valid UNKNOWN request must short-circuit
    # before attempting to read it.
    missing_typed = tmp_path / "typed-result-must-not-be-opened.json"
    convert = _run(
        "convert", "--request", str(bound), "--typed-result", str(missing_typed),
        "--output", str(result),
    )
    assert convert.returncode == 0, convert.stderr
    result_value = json.loads(result.read_text(encoding="utf-8"))
    assert result_value["schema"] == MODULE.UNKNOWN_ADMISSION_SCHEMA
    assert result_value["status"] == "UNKNOWN_REQUIRED_ROLE_PROOF"
    assert result_value["typed_content_read"] is False
    assert result_value["labels"] == []
    assert all(value is None for value in result_value["metrics"].values())
    assert result_value["adapter"]["status"] == "UNKNOWN_REQUIRED_ROLE_PROOF"

    check = _run("validate-result", "--request", str(bound), "--result", str(result))
    assert check.returncode == 0, check.stderr
    check_value = json.loads(check.stdout)
    assert check_value["status"] == "VERIFIED_UNKNOWN_METADATA_ONLY"
    assert check_value["typed_content_read"] is False
    assert check_value["read_scope"]["payload_opened"] is False


def test_v4_rejects_changed_script_binding_and_changed_source_semantics(tmp_path: Path) -> None:
    bound = tmp_path / "bound.json"
    assert MODULE.bind_request(REAL_REQUEST, bound)["adapter_schema"] == MODULE.ADAPTER_SCHEMA
    request = MODULE._read_json(bound, role="bound request")

    changed_script = copy.deepcopy(request)
    changed_script["v4_adapter_binding"]["adapter_script_file_sha256"] = "0" * 64
    changed_script["request_sha256"] = MODULE.canonical_sha(changed_script)
    changed_script_path = tmp_path / "changed-script.json"
    changed_script_path.write_text(json.dumps(changed_script), encoding="utf-8")
    with pytest.raises(MODULE.TypedEventAdapterV4Error, match="script file SHA"):
        MODULE.validate_request_v4(changed_script, require_binding=True)

    changed_semantics = copy.deepcopy(request)
    changed_semantics["case_identity"]["family_id"] = "F7"
    changed_semantics["request_sha256"] = MODULE.canonical_sha(changed_semantics)
    with pytest.raises(MODULE.TypedEventAdapterV4Error, match="semantic fields"):
        MODULE.validate_request_v4(changed_semantics, require_binding=True)


def test_fixture_requires_explicit_allowance_and_never_becomes_production_credit() -> None:
    v2_test_path = ROOT / "tests/test_ds_data02_stage2_namespace331_v16_typed_event_adapter_v2.py"
    spec = importlib.util.spec_from_file_location("v2_fixture_helpers_for_v4", v2_test_path)
    assert spec is not None and spec.loader is not None
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    request = fixture._request()
    with pytest.raises(MODULE.TypedEventAdapterV4Error, match="not production eligible"):
        MODULE.validate_request_v4(request)
    context = MODULE.validate_request_v4(request, allow_fixture=True)
    assert context["production_eligible"] is False
    document = MODULE.build_event_stream_from_request(
        fixture._typed_result(), request, allow_fixture=True,
    )
    assert document["adapter"]["schema"] == MODULE.ADAPTER_SCHEMA
    assert document["adapter"]["production_eligible"] is False
    assert document["adapter"]["event_credit"] == "DEVELOPMENT_UNKNOWN"
