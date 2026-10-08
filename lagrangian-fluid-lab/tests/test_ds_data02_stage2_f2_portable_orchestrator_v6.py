from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_orchestrator_v6.py"
SPEC = importlib.util.spec_from_file_location("portable_orchestrator_v6_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v6-f2-orchestration/"
    "f2-s1-portable-orchestration-request-v6-001.json"
)


def test_real_v6_request_is_canonical_and_binds_copy_seal_order() -> None:
    value = json.loads(REQUEST.read_text())
    assert value["schema"] == module.SCHEMA
    assert value["sha256"] == module.canonical_sha(value)
    assert value["model_invoked"] is False
    assert value["cfd_invoked"] is False
    assert value["qualification"] == module.UNKNOWN
    assert value["copy_contract"]["entry_count"] == 443
    assert value["copy_contract"]["target_root_must_be_absent_before_copy"] is True
    assert value["copy_contract"]["destination_files_must_be_absent"] is True
    assert value["copy_contract"]["original_path_fallback"] == "FORBIDDEN"
    assert value["execution"]["copy_before_raw_read"] is True
    assert value["execution"]["seal_before_raw_read"] is True
    assert value["execution"]["os_open_audit_required"] is True
    assert value["execution"]["private_fresh_python_subprocess"] is True
    assert value["execution"]["private_subprocess_bytecode"].startswith("-B")
    assert value["execution"]["original_module_cache"] == "unavailable in fresh child interpreter"
    assert value["evaluator_contract"]["model_invoked"] is False
    assert value["evaluator_contract"]["status"] == "BOUND_CONTRACT_PENDING_COMPATIBLE_RAW_RESULT_ADAPTER"
    assert len(value["source_bindings"]) == len(value["input_files"]) == 450
    assert all(isinstance(item["sha256"], str) and len(item["sha256"]) == 64 for item in value["source_bindings"])


def test_private_loader_program_has_closed_path_and_module_closure_receipt() -> None:
    program = module._private_loader_program()
    assert "sys.path[:]" in program
    assert "PYTHONPATH" not in program or "module_files" in program
    assert "forbidden_module_files" in program
    assert "PRIVATE_SUBPROCESS_MODULE_CLOSURE_FAILED" in program


def test_v6_metadata_preflight_reads_only_stats() -> None:
    value = json.loads(REQUEST.read_text())
    summary = module._validate_request(value, verify_metadata_content=False)
    assert summary["sources"] == 450
    assert summary["copy_entries"] == 443
    assert summary["source_bytes"] == sum(item["bytes"] for item in value["source_bindings"])


def test_v6_copy_handles_shared_parent_and_refuses_existing_target(tmp_path: Path) -> None:
    source_a = tmp_path / "source-a.bin"
    source_b = tmp_path / "source-b.bin"
    source_a.write_bytes(b"abc")
    source_b.write_bytes(b"defgh")
    target = tmp_path / "fresh-target"

    def item(role: str, source: Path, relative: str) -> dict:
        return {
            "role": role,
            "original_path": str(source),
            "target_path": str(target / relative),
            "bundle_relative_path": relative,
            "expected_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "expected_bytes": source.stat().st_size,
        }

    overlay = {"target_root": str(target), "entries": [
        item("same_parent_a", source_a, "shared/file-a.bin"),
        item("same_parent_b", source_b, "shared/file-b.bin"),
    ]}
    result = module._copy_overlay_entries(overlay)
    assert result["entry_count"] == 2
    assert (target / "shared/file-a.bin").read_bytes() == b"abc"
    assert (target / "shared/file-b.bin").read_bytes() == b"defgh"
    with pytest.raises(module.OrchestrationV6Error, match="already exists"):
        module._copy_overlay_entries(overlay)


def test_v6_rejects_promoted_model_and_unsealed_copy_contract() -> None:
    value = json.loads(REQUEST.read_text())
    bad = copy.deepcopy(value)
    bad["model_invoked"] = True
    bad["sha256"] = module.canonical_sha(bad)
    with pytest.raises(module.OrchestrationV6Error, match="model-free"):
        module._validate_request(bad)

    bad = copy.deepcopy(value)
    bad["copy_contract"]["original_path_fallback"] = "ALLOWED"
    bad["sha256"] = module.canonical_sha(bad)
    with pytest.raises(module.OrchestrationV6Error, match="original fallback"):
        module._validate_request(bad)
