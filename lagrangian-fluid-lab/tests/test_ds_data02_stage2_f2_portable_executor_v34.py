from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v34.py"
SPEC = importlib.util.spec_from_file_location("portable_executor_v34_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v34 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v34)


def _real(path: str) -> Path:
    return ROOT / path


def test_v34_request_is_metadata_only_and_uses_venv(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    v34.build_request(
        v31_request=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v31-full-chain/"
            "f2-s1-external-supervisor-request-v25-034.json"),
        v31_contract=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v31-full-chain/"
            "f2-s1-portable-v29-bundle-contract-v31-034.json"),
        bundle=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v5/"
            "f2-s1-native-raw-to-label-bundle-v5-003.json"),
        overlay=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v5/"
            "f2-s1-native-raw-portable-overlay-v5-003.json"),
        evaluator=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26/"
            "f2-s1-no-model-evaluator-v4-actual-request-003.json"),
        target_root=tmp_path / "target", output_root=tmp_path / "output", output=request)
    report = v34.preflight(request, tmp_path / "preflight.json")
    assert report["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert report["source_entry_count"] == 443
    assert report["content_hash_read"] is False
    assert report["hdf5_or_bi4_read"] is False
    value = json.loads(request.read_text())
    assert value["schema"].endswith(".v34")
    python = next(item for item in value["runtime_sources"]
                  if item["role"] == "python_executable")
    assert python["path"].endswith("/.venv/bin/python")
    assert value["execution"]["original_path_fallback"] == "FORBIDDEN"


def test_v34_private_audit_accepts_mapping_and_copied_sibling(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "sibling.py").write_text("VALUE = 7\n")
    (runtime / "main.py").write_text("import sibling\nVALUE = sibling.VALUE\n")
    output = tmp_path / "audit.json"
    result = v34._private_audit(
        Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"),
        runtime, {"main": str(runtime / "main.py"), "sibling": str(runtime / "sibling.py")}, output)
    assert all(item["under_runtime"] for item in result.values())
    assert json.loads(output.read_text())["status"] == "PASS_CLOSED_RUNTIME_MODULE_FILES"
