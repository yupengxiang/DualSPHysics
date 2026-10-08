from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_orchestrator_v7.py"
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v7-f2-orchestration/"
    "f2-s1-portable-orchestration-request-v7-001.json"
)
SPEC = importlib.util.spec_from_file_location("portable_orchestrator_v7_test_module", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_v7_request_is_canonical_and_uses_private_subprocess() -> None:
    request = json.loads(REQUEST.read_text())
    assert request["schema"] == module.SCHEMA
    assert request["sha256"] == module.canonical_sha(request)
    assert request["qualification"] == module.UNKNOWN
    assert request["copy_contract"]["original_path_fallback"] == "FORBIDDEN"
    assert request["execution"]["private_fresh_python_subprocess"] is True
    assert request["execution"]["original_module_cache"] == "unavailable in fresh child interpreter"
    assert len(request["source_bindings"]) == 450
    assert request["copy_contract"]["entry_count"] == 443
    assert request["copy_contract"]["target_root"].endswith("bundle-target-v7-001")
    assert request["execution"]["output_dir"].endswith("reference-products-v7-001")


def test_v7_metadata_preflight_is_stat_only() -> None:
    request = json.loads(REQUEST.read_text())
    summary = module._validate_request(request, verify_metadata_content=False)
    assert summary == {"sources": 450, "source_bytes": sum(item["bytes"] for item in request["source_bindings"]), "copy_entries": 443}


def test_v7_private_child_accepts_system_sitecustomize_but_only_relocated_loader(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    loader = runtime / "portable" / "fake_loader.py"
    loader.parent.mkdir(parents=True)
    loader.write_text(
        "def run_portable(bundle, overlay, output, *, io_slot_approved, rehash_after_copy):\n"
        "    return {'status': 'COMPLETE_DEVELOPMENT_UNKNOWN', 'model_invoked': False}\n"
    )
    bundle = tmp_path / "bundle.json"
    sealed = tmp_path / "sealed.json"
    bundle.write_text("{}\n")
    sealed.write_text("{}\n")
    output = tmp_path / "output"
    output.mkdir()
    result = module._run_private_loader(loader, bundle, sealed, output, runtime)
    assert result["status"] == "PRIVATE_SUBPROCESS_COMPLETE"
    assert result["fresh_interpreter"] is True
    assert result["loader_module_file"] == str(loader.resolve())
    assert result["forbidden_module_files"] == []
    assert result["result"]["status"] == "COMPLETE_DEVELOPMENT_UNKNOWN"
