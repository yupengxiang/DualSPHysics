from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_evaluator_parent_v2.py"
V34_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v34-full-chain/"
    "f2-s1-portable-executor-request-v34-042.json")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


parent = _load(SCRIPT, "evaluator_parent_v2_test")


def test_literal_venv_evaluator_command_and_filtered_trace(tmp_path: Path) -> None:
    v34 = json.loads(V34_REQUEST.read_text())
    proof = tmp_path / "fresh-proof.json"
    proof.write_text(json.dumps({"labels": {"v16_sha256": "0" * 64}}))
    trace = tmp_path / "trace"
    request = {"source_request": {"path": str(V34_REQUEST), "sha256": parent.sha256_file(V34_REQUEST)},
               "proof": {"path": str(proof)},
               "execution": {"strace": {"path": "/usr/bin/strace"}},}
    bound = {"request": request, "product": {"v34": v34}, "trace_path": trace,
             "max_wall": 300.0}
    command = parent._child_command(bound, 12345)
    assert command[:7] == ["/usr/bin/strace", "-ff", "-e", "trace=%file,%process", "-s", "4096", "-o"]
    assert command[7] == str(trace)
    assert command[9] == "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python"
    assert "/usr/bin/python3.10" not in command[9]


def test_existing_fresh_roots_are_validated_against_new_proof_without_h5(tmp_path: Path) -> None:
    output_root = tmp_path / "existing-output"
    target_root = tmp_path / "existing-target"
    output_root.mkdir()
    target_root.mkdir()
    result = output_root / "v16-result.json"
    result.write_text(json.dumps({"status": "labels"}))
    result_sha = parent.sha256_file(result)
    raw_report = output_root / "raw-report.json"
    raw_report.write_text(json.dumps({"typed_to_label": {"v16_forward": {"result": str(result)}}}))
    executor_report = output_root / "portable-executor-report-v34.json"
    executor_report.write_text(json.dumps({
        "original_path_fallback": "FORBIDDEN",
        "stages": {"raw_to_typed_to_label": {"report": str(raw_report)}},
    }))
    proof = tmp_path / "new-proof.json"
    proof.write_text(json.dumps({"labels": {"v16_sha256": result_sha},
                                 "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}))
    v34 = json.loads(V34_REQUEST.read_text())
    v34["fresh_roots"] = {"output_root": str(output_root), "target_root": str(target_root)}
    v34["sha256"] = parent.canonical_sha(v34)
    source = tmp_path / "v34-request.json"
    source.write_text(json.dumps(v34))
    request = {"source_request": {"path": str(source), "sha256": parent.sha256_file(source)},
               "proof": {"path": str(proof), "sha256": parent.sha256_file(proof), "forbidden_sha256": "f" * 64}}
    metadata = parent._validate_fresh_product(request, proof, verify_result_content=False)
    assert metadata["result_sha_verified"] is False
    product = parent._validate_fresh_product(request, proof, verify_result_content=True)
    assert product["output_root"] == output_root.resolve()
    assert product["target_root"] == target_root.resolve()
    assert product["result_sha256"] == result_sha


def test_metadata_pass_does_not_digest_large_result(tmp_path: Path, monkeypatch) -> None:
    output_root = tmp_path / "existing-output"
    target_root = tmp_path / "existing-target"
    output_root.mkdir()
    target_root.mkdir()
    result = output_root / "v16-result.json"
    result.write_text("x" * 1024)
    result_sha = parent.sha256_file(result)
    raw_report = output_root / "raw-report.json"
    raw_report.write_text(json.dumps({"typed_to_label": {"v16_forward": {"result": str(result)}}}))
    executor_report = output_root / "portable-executor-report-v34.json"
    executor_report.write_text(json.dumps({
        "original_path_fallback": "FORBIDDEN",
        "stages": {"raw_to_typed_to_label": {"report": str(raw_report)}},
    }))
    proof = tmp_path / "new-proof.json"
    proof.write_text(json.dumps({"labels": {"v16_sha256": result_sha},
                                 "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}))
    v34 = json.loads(V34_REQUEST.read_text())
    v34["fresh_roots"] = {"output_root": str(output_root), "target_root": str(target_root)}
    source = tmp_path / "v34-request.json"
    source.write_text(json.dumps(v34))
    request = {"source_request": {"path": str(source), "sha256": parent.sha256_file(source)},
               "proof": {"path": str(proof), "sha256": parent.sha256_file(proof), "forbidden_sha256": "f" * 64}}
    original = parent.sha256_file
    seen: list[Path] = []

    def tracking(path):
        resolved = Path(path).expanduser().resolve()
        seen.append(resolved)
        return original(path)

    monkeypatch.setattr(parent, "sha256_file", tracking)
    product = parent._validate_fresh_product(request, proof, verify_result_content=False)
    assert product["result_sha256"] == result_sha
    assert result.resolve() not in seen


def test_stop_group_reaps_nested_owned_helper(tmp_path: Path) -> None:
    import os
    import subprocess
    import sys
    import time

    code = (
        "import subprocess,sys,time,signal; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "time.sleep(30)"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], start_new_session=True)
    try:
        result = parent._stop_group(proc, 0.3)
        assert result["reaped"] is True
        assert result["group_gone"] is True
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def test_historical_proof_hash_is_explicitly_forbidden() -> None:
    assert "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47" in parent.OLD_F2_PROOF_SHA256
    assert parent.THREAD_ENV == {
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
        "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    }
