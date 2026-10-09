from __future__ import annotations

import importlib.util
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v62.py"
V61_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v61b-root145-source-closure-20261009/"
    "f2-s1-root145-v61b-source-closure-parent-request.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("v62_test_module", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_worker():
    worker_script = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v62.py"
    spec = importlib.util.spec_from_file_location("v62_worker_test_module", worker_script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _raw_fixture(tmp_path: Path):
    module = _load()
    root = tmp_path / "bundle-target"
    root.mkdir()
    names = ["Part_0000.bi4", "Part_0001.bi4", *module.RAW_AUXILIARY_NAMES]
    for index, name in enumerate(names):
        (root / name).write_bytes(f"raw-{index}".encode())
    # These are deliberately present in the relocated bundle but are outside
    # the producer raw role.  A generated H5 is not a raw-copy event.
    (root / "sources").mkdir()
    (root / "sources" / "worker.py").write_text("# copied code\n")
    (root / "products").mkdir()
    (root / "products" / "typed-reconstructed.h5").write_bytes(b"generated")
    scope = sorted(names)
    observed = module._raw_tree_manifest(root, scope)
    return module, root, scope, observed


def test_v62_manifest_is_exact_producer_scope_and_ignores_bundle_code(tmp_path):
    module, root, scope, observed = _raw_fixture(tmp_path)
    checked = module._raw_tree_manifest(root, scope, observed["tree_sha256"])
    assert checked["file_count"] == 6
    assert checked["tree_sha256"] == observed["tree_sha256"]
    assert all(item["path"] in scope for item in checked["files"])
    try:
        module._raw_tree_manifest(root)
    except module.PortableV62Error as error:
        assert "explicit producer scope" in str(error)
    else:  # pragma: no cover
        raise AssertionError("V62 accepted an unscoped recursive manifest")


def test_v62_copy_counter_does_not_count_generated_h5(tmp_path):
    module, root, scope, _observed = _raw_fixture(tmp_path)
    output = tmp_path / "products"
    supervisor = tmp_path / "supervisor"
    output.mkdir()
    supervisor.mkdir()
    (output / "typed-reconstructed.h5").write_bytes(b"generated")
    assert module._payload_copy_count(root, output, supervisor, scope) == len(scope)
    # Once only the generated product remains in a fresh target, no payload
    # copy is attributed to it.
    for item in scope:
        (root / item).unlink()
    assert module._payload_copy_count(root, output, supervisor, scope) == 0


def test_v62_actual_v60_graph_builds_405_scope_and_rebases_all_actionable_modules(tmp_path):
    module = _load()
    external = tmp_path / "external"
    external.mkdir()
    output_request = tmp_path / "v62-request.json"
    target = external / "v62" / "bundle-target"
    output = external / "v62" / "products"
    supervisor = external / "v62" / "supervisor"
    ledger = json.loads(
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
        .read_text(encoding="utf-8")
    )
    # The builder reads the live ledger but does not mutate it or read the raw
    # payload.  Use a real copy of its small metadata under the test root.
    ledger_path = tmp_path / "resource-ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    result = module.build_request(
        v61_request=V61_REQUEST,
        output_request=output_request,
        target_root=target,
        output_root=output,
        supervisor_root=supervisor,
        ledger=ledger_path,
        external_filesystem=external,
        home=tmp_path,
        home_receipt=tmp_path / "home-receipt.json",
        max_wall_seconds=10.0,
    )
    assert result["payload_read"] is False
    request = json.loads(output_request.read_text(encoding="utf-8"))
    assert request["raw_source"]["file_count"] == 405
    assert len(request["raw_source"]["scope_paths"]) == 405
    assert request["raw_source"]["scope"] == "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V62"
    assert request["storage_scope"]["home_receipt_bytes"] >= 1024 * 1024
    run_out = request["run_out_binding"]
    assert Path(run_out["source_path"]).name == "Run.out"
    assert Path(run_out["target_path"]) == target / "sources/0020-solver-Run.out"
    assert run_out["source_path"] != run_out["target_path"]
    assert len(run_out["expected_sha256"]) == 64
    embedded = request["embedded_worker_request"]
    for role, item in embedded["modules"].items():
        assert str(target / "runtime/native") in item["path"]
        assert all(stale not in item["path"] for stale in ("V58", "V58D", "V59", "V59B"))
        assert item["sha256"] == embedded["v62_worker_binding"]["module_sha256"][role]
    wrapper = next(item for item in request["runtime"]["code_overlay_bindings"]
                   if item["role"] == "v62_worker_wrapper")
    assert Path(wrapper["source_path"]).name == "ds_data02_stage2_f2_native_raw_to_typed_label_v62.py"
    assert Path(wrapper["target_path"]).name == Path(wrapper["source_path"]).name
    assert len(request["source_closure"]) == len(embedded["source_files"]) + len(
        embedded["v15_request"]["motion_engine_sources"])
    assert module._validate_request(output_request, verify_static=False)["scope_paths"] == request["raw_source"]["scope_paths"]


def test_v62_worker_binding_uses_real_worker_cli_and_bounded_failure_summary(tmp_path):
    module = _load()
    assert module.WORKER_SCRIPT != module.SCRIPT
    assert module.WORKER_SCRIPT.name == "ds_data02_stage2_f2_native_raw_to_typed_label_v62.py"
    missing = tmp_path / "missing-worker-request.json"
    output = tmp_path / "worker-output"
    python = module.PINNED_PYTHON if Path(module.PINNED_PYTHON).is_file() else sys.executable
    completed = subprocess.run(
        [python, str(module.WORKER_SCRIPT), "run", "--request", str(missing),
         "--output-dir", str(output), "--io-slot-approved"],
        text=True, capture_output=True, check=False, timeout=10,
    )
    assert completed.returncode == 2
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    summary = json.loads(lines[0])
    assert summary["status"] == "FAILED"
    assert len(completed.stdout.encode()) < 64 * 1024
    assert "build-request" not in completed.stdout


def test_v62_source_closure_is_after_reservation_and_rejects_wrong_sha(tmp_path):
    module = _load()
    source = tmp_path / "tiny-source.json"
    source.write_text('{"source":"bound"}\n', encoding="utf-8")
    good = {
        "role": "tiny",
        "path": str(source),
        "expected_sha256": module._sha(source),
        "source_kind": "V15_EMBEDDED_SOURCE_FILE",
        "verification_phase": "AFTER_ATOMIC_PARENT_RESERVATION_PRE_AND_POST",
        "read_by_worker": True,
    }
    observed = module._verify_source_closure([good], phase="AFTER_RESERVATION")
    assert observed[0]["sha256"] == good["expected_sha256"]
    bad = dict(good, expected_sha256="0" * 64)
    try:
        module._verify_source_closure([bad], phase="AFTER_RESERVATION")
    except module.PortableV62Error as error:
        assert "source closure SHA differs" in str(error)
    else:  # pragma: no cover
        raise AssertionError("wrong source closure SHA was accepted")


def test_v62_embedded_module_declared_sha_must_equal_expected_binding(tmp_path):
    module = _load()
    external = tmp_path / "external"
    external.mkdir()
    output_request = tmp_path / "v62-request.json"
    ledger = json.loads(
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
        .read_text(encoding="utf-8")
    )
    ledger_path = tmp_path / "resource-ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    module.build_request(
        v61_request=V61_REQUEST,
        output_request=output_request,
        target_root=external / "bundle-target",
        output_root=external / "products",
        supervisor_root=external / "supervisor",
        ledger=ledger_path,
        external_filesystem=external,
        home=tmp_path,
        home_receipt=tmp_path / "home-receipt.json",
        max_wall_seconds=10.0,
    )
    request = json.loads(output_request.read_text(encoding="utf-8"))
    request["embedded_worker_request"]["modules"]["worker"]["sha256"] = "0" * 64
    request["sha256"] = module._canonical(request)
    mutated = tmp_path / "mutated-v62.json"
    mutated.write_text(json.dumps(request), encoding="utf-8")
    try:
        module._validate_request(mutated, verify_static=False)
    except module.PortableV62Error as error:
        assert "does not match expected binding" in str(error)
    else:  # pragma: no cover
        raise AssertionError("module SHA mismatch was accepted")


def test_v62_worker_summary_uses_execution_boundary_and_typed_stat(tmp_path):
    module = _load_worker()
    output = tmp_path / "products"
    output.mkdir()
    typed = output / "typed-reconstructed-v2.h5"
    typed.write_bytes(b"tiny typed output")
    (output / "raw-to-typed-to-label-report-v2.json").write_text("{}\n", encoding="utf-8")
    result = {
        "status": "COMPLETE_DEVELOPMENT_UNKNOWN",
        "typed_output": {"path": str(typed), "sha256": "a" * 64},
        "raw_to_typed": {},
        "execution_boundary": {
            "raw_opened": True, "hdf5_opened": True, "converter_invoked": True,
            "label_operator_invoked": True, "model_invoked": False, "cfd_invoked": False,
        },
    }
    summary = module._worker_summary(result, output)
    assert summary["raw_opened"] is True
    assert summary["hdf5_opened"] is True
    assert summary["converter_invoked"] is True
    assert summary["label_operator_invoked"] is True
    assert summary["typed_output_bytes"] == typed.stat().st_size
    assert summary["execution_boundary"]["hdf5_opened"] is True


def test_v62_bounded_logs_keep_terminal_tail_after_multi_megabyte_output(tmp_path):
    module = _load()
    code = "import sys; sys.stdout.write('x' * (5 * 1024 * 1024)); print('terminal-marker', flush=True)"
    result = module._run_bounded(
        [sys.executable, "-c", code], cwd=tmp_path, env=dict(os.environ),
        timeout=10.0, cleanup_grace=0.2, parent_pid=os.getpid(),
    )
    assert result["returncode"] == 0
    assert result["timed_out"] is False
    assert result["stdout_bytes"] > 5 * 1024 * 1024
    assert result["stdout_discarded_bytes"] > 0
    assert len(result["stdout_tail"].encode()) <= module.LOG_TAIL_BYTES
    assert "terminal-marker" in result["stdout_tail"]


def test_v62_bounded_timeout_kills_descendant_that_keeps_pipe_open(tmp_path):
    module = _load()
    child = "import time; print('descendant', flush=True); time.sleep(30)"
    code = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); "
        "print('leader', flush=True)"
    )
    started = time.monotonic()
    result = module._run_bounded(
        [sys.executable, "-c", code], cwd=tmp_path, env=dict(os.environ),
        timeout=0.3, cleanup_grace=0.2, parent_pid=os.getpid(),
    )
    assert time.monotonic() - started < 3.0
    assert result["timed_out"] is True
    assert result["cleanup"].get("sigterm_sent") or result["cleanup"].get("sigkill_sent")
    assert result["cleanup"].get("group_gone") is True


def test_v62_run_out_copy_is_explicit_bounded_metadata_and_detects_mutation(tmp_path):
    module = _load()
    source = tmp_path / "Run.out"
    receipt = tmp_path / "solver-receipt.json"
    target = tmp_path / "target" / "sources" / "0020-solver-Run.out"
    source.write_bytes(b"solver log\n")
    receipt.write_text('{"output_root":"/immutable/provenance"}\n', encoding="utf-8")
    binding = {
        "source_path": str(source), "target_path": str(target),
        "expected_sha256": module._sha(source),
        "solver_receipt_path": str(receipt),
        "solver_receipt_sha256": module._sha(receipt),
    }
    copied = module._copy_bound_metadata(binding)
    assert copied["target"]["sha256"] == binding["expected_sha256"]
    assert module._verify_bound_metadata(binding, phase="TEST")["equal_sha256"] is True
    source.write_bytes(b"mutated solver log\n")
    try:
        module._verify_bound_metadata(binding, phase="TEST_MUTATION")
    except module.PortableV62Error as error:
        assert "Run.out SHA differs" in str(error)
    else:  # pragma: no cover
        raise AssertionError("Run.out mutation was not rejected")


def test_v62_v2_strict_request_accepts_only_a_complete_bound_tiny_graph(tmp_path):
    """Exercise the real V2 request gate, not just the V62 parent validator."""
    module = _load()
    v2_path = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
    spec = importlib.util.spec_from_file_location("v2_strict_fixture", v2_path)
    assert spec and spec.loader
    v2 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(v2)
    source = json.loads(V61_REQUEST.read_text(encoding="utf-8"))
    request = copy.deepcopy(source["embedded_worker_request"])
    raw_root = tmp_path / "raw"
    raw_root.mkdir()
    frames = []
    for index in range(2):
        frame = raw_root / f"Part_{index:04d}.bi4"
        frame.write_bytes(f"frame-{index}".encode())
        frames.append({"frame": index, "path": str(frame), "bytes": frame.stat().st_size,
                       "sha256": None})
    request["raw_binding"] = {"data_root": str(raw_root), "frames": frames,
                               "expected_raw_tree_sha256": "0" * 64}
    module_dir = tmp_path / "modules"
    module_dir.mkdir()
    for role in ("raw_converter", "v15_operator", "v14_operator", "v16_operator"):
        path = module_dir / f"{role}.py"
        path.write_text(f"# {role}\n", encoding="utf-8")
        request["modules"][role] = {"path": str(path), "sha256": module._sha(path)}
    required_roles = {"current_catalog", "generated_xml", "motion_dat", "gencase_receipt",
                      "solver_receipt", "owner_metadata", "initial_csv", "conversion_report",
                      "native_partout", "native_runparts"}
    for index, item in enumerate(request["source_files"]):
        role = str(item.get("role"))
        path = tmp_path / "sources" / f"{index:02d}-{role}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps({"role": role}), encoding="utf-8")
        item["path"] = str(path)
        item["sha256"] = module._sha(path)
    assert required_roles.issubset({str(item.get("role")) for item in request["source_files"]})
    request["source_hashes_preverified_by_parent"] = True
    bound = v2._require_request(request, verify_sources=False)
    assert bound["data_root"] == raw_root.resolve()
    assert len(bound["frames"]) == 2
