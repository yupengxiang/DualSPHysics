from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_portable_executor_v32.py"
SPEC = importlib.util.spec_from_file_location("portable_executor_v32_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
v32 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(v32)


def _real(path: str) -> Path:
    return ROOT / path


def test_real_v32_request_preflight_is_metadata_only(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    v32.build_request(
        v31_request=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v31-full-chain/"
            "f2-s1-external-supervisor-request-v25-034.json"
        ),
        v31_contract=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v31-full-chain/"
            "f2-s1-portable-v29-bundle-contract-v31-034.json"
        ),
        bundle=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v5/"
            "f2-s1-native-raw-to-label-bundle-v5-002.json"
        ),
        overlay=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v5/"
            "f2-s1-native-raw-portable-overlay-v5-002.json"
        ),
        evaluator=_real(
            "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v26/"
            "f2-s1-no-model-evaluator-v4-actual-request-003.json"
        ),
        target_root=tmp_path / "fresh-target",
        output_root=tmp_path / "fresh-output",
        output=request,
    )
    report = v32.preflight(request, tmp_path / "preflight.json")
    assert report["status"] == "READY_FOR_PARENT_STAGE2_GUARD"
    assert report["hdf5_or_bi4_read"] is False
    assert report["content_hash_read"] is False
    assert report["source_entry_count"] == 443
    assert report["original_path_fallback"] == "FORBIDDEN"
    value = json.loads(request.read_text())
    python_binding = next(item for item in value["runtime_sources"]
                          if item["role"] == "python_executable")
    assert python_binding["path"].endswith("/.venv/bin/python")
    assert value["execution"]["command"][0].endswith("/.venv/bin/python")


def test_overlay_rebinds_every_target_and_rejects_old_root(tmp_path: Path) -> None:
    source_a = tmp_path / "source" / "a.txt"
    source_b = tmp_path / "source" / "nested" / "b.txt"
    source_a.parent.mkdir(parents=True)
    source_b.parent.mkdir(parents=True)
    source_a.write_text("a\n")
    source_b.write_text("b\n")
    template = {
        "schema": "ds02.stage2.f2-native-raw-portable-overlay.v5",
        "sha256": "pending",
        "entries": [
            {"role": "runtime_a", "bundle_relative_path": "runtime/a.txt",
             "original_path": str(source_a), "expected_bytes": source_a.stat().st_size,
             "expected_sha256": v32.sha256_file(source_a)},
            {"role": "raw_frame_input", "bundle_relative_path": "raw/b.txt",
             "original_path": str(source_b), "expected_bytes": source_b.stat().st_size,
             "expected_sha256": v32.sha256_file(source_b)},
        ],
    }
    template["sha256"] = v32.canonical_sha(template)
    rebound = v32._overlay_from_template(template, tmp_path / "new-target")
    assert all(str(tmp_path / "new-target") in item["target_path"]
               for item in rebound["entries"])
    assert all(str(tmp_path / "source") not in item["target_path"]
               for item in rebound["entries"])
    assert rebound["original_path_fallback"] == "FORBIDDEN"


def test_copy_seal_rejects_same_size_wrong_content(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    target = tmp_path / "target.bin"
    source.write_bytes(b"correct")
    with pytest.raises(v32.PortableExecutorError):
        v32._copy_one(source, target, "0" * 64, source.stat().st_size)
    assert target.is_file()
    target.write_bytes(b"wrong!!")
    with pytest.raises(v32.PortableExecutorError):
        v32._copy_one(source, target, v32.sha256_file(source), source.stat().st_size)


def test_private_module_audit_uses_target_files_only(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    module = runtime / "module.py"
    module.write_text("VALUE = 1\n")
    output = tmp_path / "audit.json"
    python = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
    result = v32._private_audit(python, runtime, {"module": str(module)}, output)
    assert result["module"]["under_runtime"] is True
    value = json.loads(output.read_text())
    assert value["fresh_interpreter"] is True
    assert value["original_path_fallback"] == "FORBIDDEN"
