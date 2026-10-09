"""Source-only V64 scratch/bootstrap contract tests.

These tests deliberately use tiny files and a fake decoder module.  They do
not open a native Part file, HDF5, result JSON, or run a parent guard.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import shutil
import tempfile
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
WORKER_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v64.py"
BOOTSTRAP_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_v64_bootstrap.py"
FRESH_REQUEST_BUILDER = SCRIPT_DIR / "ds_data02_stage2_f2_v64_fresh_v16_proof_request.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def worker():
    return _load(WORKER_PATH, "test_v64_worker_scratch")


def test_scratch_binding_rejects_shared_tmp_and_requires_fresh_external_child(worker, tmp_path):
    external = tmp_path / "external"
    external.mkdir()
    output = external / "products"
    output.mkdir()

    def contract(root: Path):
        return {"runtime": {"scratch": {
            "root": str(root), "external_root": str(external),
            "max_frame_bytes": 512 * 1024 * 1024, "timeout_seconds": 2,
        }}}

    with pytest.raises(worker.V64WorkerError):
        worker._scratch_binding(contract(Path("/tmp/v64-test-scratch")), output)
    with pytest.raises(worker.V64WorkerError, match="scratch root"):
        worker._scratch_binding(contract(tmp_path / "other" / "scratch"), output)

    fresh = external / "attempt" / "decoder-scratch"
    value = worker._scratch_binding(contract(fresh), output)
    assert value["root"] == fresh
    assert value["external_root"] == external

    fresh.mkdir(parents=True)
    (fresh / "leftover").write_text("must reject", encoding="utf-8")
    with pytest.raises(worker.V64WorkerError, match="fresh and empty"):
        worker._scratch_binding(contract(fresh), output)


def test_decoder_frame_is_hard_capped_and_cleaned_after_failure(worker, tmp_path):
    external = tmp_path / "external"
    output = external / "products"
    output.mkdir(parents=True)
    scratch_root = external / "attempt" / "decoder-scratch"
    contract = {
        "root": scratch_root,
        "external_root": external,
        "max_frame_bytes": 8,
        "timeout_seconds": 2.0,
        "attempt_id": "tiny-v64",
    }
    fake = types.SimpleNamespace()
    fake.tempfile = __import__("tempfile")
    fake.subprocess = __import__("subprocess")

    def decode(_frame, _decoder, frame_scratch, index):
        frame_dir = Path(frame_scratch) / f"frame_{index:04d}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        (frame_dir / "payload").write_bytes(b"0123456789")
        return object()

    fake.decode_frame = decode
    worker._configure_converter_scratch(fake, contract, output)
    private = scratch_root / "decoder-child"
    private.mkdir(parents=True)
    with pytest.raises(worker.V64WorkerError, match="hard bound"):
        fake.decode_frame(Path("frame.bi4"), Path("decoder"), private, 0)
    report = worker._restore_converter_scratch(fake, contract)
    assert report["peak_frame_bytes"] == 10
    assert report["cleaned_frames"] == 1
    assert not (private / "frame_0000").exists()
    # The attempt-owned root is the executor's terminal cleanup responsibility.
    import shutil
    shutil.rmtree(scratch_root.parent)


def test_bootstrap_loads_only_copied_sibling_and_preserves_worker_argv(tmp_path):
    root = tmp_path / "runtime-native"
    root.mkdir()
    (root / "ds_data02_stage2_f2_replay_v14.py").write_text(
        "CANONICAL = 'copied'\n", encoding="utf-8")
    worker = root / "worker.py"
    worker.write_text(
        "import ds_data02_stage2_f2_replay_v14\n"
        "def main(argv):\n"
        "    print(__file__)\n"
        "    print(ds_data02_stage2_f2_replay_v14.CANONICAL)\n"
        "    print(argv)\n"
        "    return 0\n", encoding="utf-8")
    command = [sys.executable, "-I", str(BOOTSTRAP_PATH),
               "--runtime-root", str(root), "--worker", str(worker), "--",
               "run", "--request", str(root / "request.json")]
    result = subprocess.run(command, check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[0] == str(worker)
    assert lines[1] == "copied"
    assert lines[2:] == ["['run', '--request', '" + str(root / "request.json") + "']"]


def test_bootstrap_rejects_worker_outside_canonical_root(tmp_path):
    root = tmp_path / "runtime-native"
    root.mkdir()
    outside = tmp_path / "outside.py"
    outside.write_text("def main(argv): return 0\n", encoding="utf-8")
    command = [sys.executable, "-I", str(BOOTSTRAP_PATH),
               "--runtime-root", str(root), "--worker", str(outside), "--", "run"]
    result = subprocess.run(command, check=False, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert result.returncode != 0
    assert "outside" in result.stderr


def test_v64_source_only_builder_and_parent_metadata_preflight():
    """The real frozen V62 graph gets a V64 command without payload reads."""
    executor = _load(
        SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v64.py",
        "test_v64_executor_builder",
    )
    v62_path = (ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/"
                "raw-to-label-v62-root145-runout-20261009/"
                "f2-s1-root145-v62c-runout-parent-request.json")
    assert v62_path.is_file(), f"frozen V62C source graph is unavailable: {v62_path}"
    v62 = json.loads(v62_path.read_text(encoding="utf-8"))
    base = Path(tempfile.mkdtemp(prefix="v64-source-only-builder-"))
    try:
        result = executor.build_request(
            v62_request=v62_path,
            output_request=base / "parent-request.json",
            target_root=base / "bundle-target",
            output_root=base / "products",
            ledger=v62["parent_resource_binding"]["ledger_path"],
            external_filesystem=base,
            home="/home/jade",
            home_receipt=base / "home-receipt.json",
            supervisor_root=base / "supervisor",
            attempt_id="v64-source-only-test",
        )
        assert result["payload_read"] is False
        assert result["raw_copy_bytes"] == 0
        request = json.loads((base / "parent-request.json").read_text(encoding="utf-8"))
        bound = executor._validate_request(base / "parent-request.json", verify_static=False)
        assert bound["bootstrap_target"].name == "ds_data02_stage2_f2_v64_bootstrap.py"
        command = request["execution"]["command"]
        assert command[3] == str(bound["bootstrap_target"])
        assert command[8] == "--"
        scratch = request["runtime"]["scratch"]
        assert scratch["root"].startswith(str(base))
        assert scratch["default_tmp_forbidden"] is True
        assert request["storage_scope"]["source_copy_bytes"] == 0
        assert request["fresh_cold_credit"] is False
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_decoder_pipe_is_drained_and_only_bounded_tail_is_retained(worker, tmp_path):
    """A noisy decoder cannot block on stderr and its full byte count is kept."""
    external = tmp_path / "external"
    output = external / "products"
    output.mkdir(parents=True)
    scratch_root = external / "attempt" / "decoder-scratch"
    decoder = tmp_path / "noisy-decoder.py"
    decoder.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "sys.stderr.write('x' * (256 * 1024))\n"
        "sys.stderr.flush()\n",
        encoding="utf-8",
    )
    decoder.chmod(0o755)
    contract = {
        "root": scratch_root,
        "external_root": external,
        "max_frame_bytes": 1024 * 1024,
        "timeout_seconds": 5.0,
        "attempt_id": "noisy-decoder",
    }
    fake = types.SimpleNamespace()
    fake.tempfile = __import__("tempfile")
    fake.subprocess = __import__("subprocess")

    def decode(_frame, decoder_path, frame_scratch, index):
        frame_dir = Path(frame_scratch) / f"frame_{index:04d}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        fake.subprocess.run(
            [str(decoder_path), str(_frame), str(frame_dir)],
            check=True, stdout=fake.subprocess.DEVNULL,
            stderr=fake.subprocess.PIPE, text=True, timeout=2.0,
        )
        return object()

    fake.decode_frame = decode
    worker._configure_converter_scratch(fake, contract, output)
    private = scratch_root / "decoder-child"
    private.mkdir(parents=True)
    with pytest.raises(worker.V64WorkerError, match="capture_output"):
        fake.subprocess.run(
            [str(decoder), "frame.bi4", str(private / "frame_0000")],
            capture_output=True,
        )
    fake.decode_frame(Path("frame.bi4"), decoder, private, 0)
    report = worker._restore_converter_scratch(fake, contract)
    assert report["decoder_stderr_bytes"] == 256 * 1024
    assert report["decoder_stderr_discarded_bytes"] == 256 * 1024 - worker.DECODER_LOG_TAIL_BYTES
    assert len(report["decoder_stderr_tail"].encode("utf-8")) == worker.DECODER_LOG_TAIL_BYTES
    assert set(report["decoder_stderr_tail"]) == {"x"}
    assert report["cleaned_frames"] == 1
    shutil.rmtree(scratch_root.parent)


def _script(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o755)
    return path


def _decoder_contract(external: Path, *, max_frame: int = 1024 * 1024,
                      timeout: float = 2.0) -> dict:
    return {
        "root": external / "attempt" / "decoder-scratch",
        "external_root": external,
        "max_frame_bytes": max_frame,
        "timeout_seconds": timeout,
        "attempt_id": "decoder-lifecycle",
    }


def _run_script_decoder(worker, script: Path, contract: dict, output: Path,
                        *, index: int = 0):
    fake = types.SimpleNamespace()
    fake.tempfile = __import__("tempfile")
    fake.subprocess = __import__("subprocess")

    def decode(_frame, decoder_path, frame_scratch, frame_index):
        frame_dir = Path(frame_scratch) / f"frame_{frame_index:04d}"
        frame_dir.mkdir(parents=True, exist_ok=True)
        fake.subprocess.run(
            [str(decoder_path), str(_frame), str(frame_dir)],
            check=True, stdout=fake.subprocess.DEVNULL,
            stderr=fake.subprocess.PIPE, text=True, timeout=contract["timeout_seconds"],
        )
        return object()

    fake.decode_frame = decode
    worker._configure_converter_scratch(fake, contract, output)
    private = contract["root"] / "decoder-child"
    private.mkdir(parents=True)
    started = time.monotonic()
    try:
        fake.decode_frame(Path("frame.bi4"), script, private, index)
    finally:
        elapsed = time.monotonic() - started
        report = worker._restore_converter_scratch(fake, contract)
    return elapsed, report, contract["root"]


def _assert_pid_gone(pid: int) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        proc_stat = Path(f"/proc/{pid}/stat")
        if not proc_stat.exists():
            return
        try:
            state = proc_stat.read_text(encoding="ascii").split()[2]
        except (FileNotFoundError, ProcessLookupError):
            return
        if state == "Z":
            return
        time.sleep(0.02)
    raise AssertionError(f"owned decoder PID remains alive: {pid}")


def test_decoder_timeout_kills_owned_session_and_cleans_frame(worker, tmp_path):
    external = tmp_path / "external"
    output = external / "products"
    output.mkdir(parents=True)
    pid_file = tmp_path / "timeout.pid"
    decoder = _script(
        tmp_path / "sleep-decoder.py",
        "import os, pathlib, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "time.sleep(10)\n",
    )
    contract = _decoder_contract(external, timeout=0.15)
    with pytest.raises(subprocess.TimeoutExpired):
        _run_script_decoder(worker, decoder, contract, output)
    pid = int(pid_file.read_text(encoding="utf-8"))
    _assert_pid_gone(pid)
    assert contract["root"].is_dir()
    assert not any(item.is_file() for item in contract["root"].rglob("*"))


def test_decoder_live_scratch_cap_kills_owned_session(worker, tmp_path):
    external = tmp_path / "external"
    output = external / "products"
    output.mkdir(parents=True)
    pid_file = tmp_path / "cap.pid"
    decoder = _script(
        tmp_path / "cap-decoder.py",
        "import os, pathlib, sys, time\n"
        f"pathlib.Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "pathlib.Path(sys.argv[2], 'payload').write_bytes(b'x' * 64)\n"
        "time.sleep(10)\n",
    )
    contract = _decoder_contract(external, max_frame=8, timeout=5.0)
    with pytest.raises(worker.V64WorkerError, match="hard cap"):
        _run_script_decoder(worker, decoder, contract, output)
    pid = int(pid_file.read_text(encoding="utf-8"))
    _assert_pid_gone(pid)
    assert contract["root"].is_dir()
    assert not any(item.is_file() for item in contract["root"].rglob("*"))


def test_decoder_leader_exit_with_pipe_holder_is_reaped(worker, tmp_path):
    external = tmp_path / "external"
    output = external / "products"
    output.mkdir(parents=True)
    child_pid_file = tmp_path / "holder.pid"
    decoder = _script(
        tmp_path / "holder-decoder.py",
        "import os, pathlib, sys, time\n"
        "child = os.fork()\n"
        "if child == 0:\n"
        f"    pathlib.Path({str(child_pid_file)!r}).write_text(str(os.getpid()))\n"
        "    time.sleep(10)\n"
        "    os._exit(0)\n"
        "os._exit(0)\n",
    )
    contract = _decoder_contract(external, timeout=5.0)
    elapsed, report, root = _run_script_decoder(worker, decoder, contract, output)
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    _assert_pid_gone(child_pid)
    assert elapsed < worker.DECODER_POST_EXIT_DRAIN_SECONDS + 1.0
    assert report["decoder_stderr_bytes"] == 0
    assert root.is_dir()
    assert not any(item.is_file() for item in root.rglob("*"))


def test_fresh_v16_builder_uses_only_new_v64_metadata_and_rejects_stale_proof(tmp_path):
    builder = _load(FRESH_REQUEST_BUILDER, "test_v64_fresh_v16_builder")
    zeros = "0" * 64
    report = {
        "schema": "ds02.stage2.f2-root145-copied-recovery-report.v64",
        "status": "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN",
        "request": {"path": str(tmp_path / "v64-parent.json"), "sha256": zeros},
        "typed_output_contract": {"path": str(tmp_path / "new-v64-typed.h5"),
                                   "sha256": "1" * 64, "bytes": 123,
                                   "parent_rehashed": False},
        "raw_source": {"expected_tree_sha256": "2" * 64},
        "source_closure": {"prepost_equal": True},
    }
    summary = {
        "schema": "ds02.stage2.f2-native-raw-to-typed-to-label-worker-summary.v64",
        "status": "COMPLETED_RAW_TYPED_LABEL_UNKNOWN",
        "summary_path": str(tmp_path / "v64-worker-summary.json"),
        "typed_output_report_contract": {"path": str(tmp_path / "new-v64-typed.h5"),
                                          "sha256": "1" * 64, "bytes": 123},
    }
    source = {"current_case_id": "F2_CASE_078",
              "current_source_sha256": "3" * 64,
              "runtime_view_sha256": "4" * 64}
    report_path = tmp_path / "v64-report.json"
    summary_path = tmp_path / "v64-summary.json"
    source_path = tmp_path / "fresh-source-contract.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    source_path.write_text(json.dumps(source), encoding="utf-8")
    result = builder.build_requests(
        v64_report=report_path, worker_summary=summary_path,
        source_contract=source_path,
        output_proof=tmp_path / "fresh-proof.json",
        output_evaluator=tmp_path / "fresh-evaluator.json",
        attempt_id="fresh-v16-test",
    )
    assert result["payload_read"] is False
    proof = json.loads((tmp_path / "fresh-proof.json").read_text(encoding="utf-8"))
    evaluator = json.loads((tmp_path / "fresh-evaluator.json").read_text(encoding="utf-8"))
    assert proof["producer"]["typed_output"]["sha256"] == "1" * 64
    assert evaluator["old_proof_reuse"] is False
    stale_source = dict(source)
    stale_source["provenance"] = "/old-proof/ROOT060/aabfb"
    stale_path = tmp_path / "stale-source.json"
    stale_path.write_text(json.dumps(stale_source), encoding="utf-8")
    with pytest.raises(builder.FreshV16RequestError, match="stale"):
        builder.build_requests(
            v64_report=report_path, worker_summary=summary_path,
            source_contract=stale_path,
            output_proof=tmp_path / "stale-proof.json",
            output_evaluator=tmp_path / "stale-evaluator.json",
            attempt_id="fresh-v16-stale-test",
        )
