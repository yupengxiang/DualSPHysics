from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v61.py"
V60_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v60-root145-explicit-raw-scope-20261009/"
    "f2-s1-root145-v60b-explicit-raw-scope-parent-request.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("v61_test_module", SCRIPT)
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


def test_v61_manifest_is_exact_producer_scope_and_ignores_bundle_code(tmp_path):
    module, root, scope, observed = _raw_fixture(tmp_path)
    checked = module._raw_tree_manifest(root, scope, observed["tree_sha256"])
    assert checked["file_count"] == 6
    assert checked["tree_sha256"] == observed["tree_sha256"]
    assert all(item["path"] in scope for item in checked["files"])
    try:
        module._raw_tree_manifest(root)
    except module.PortableV61Error as error:
        assert "explicit producer scope" in str(error)
    else:  # pragma: no cover
        raise AssertionError("V61 accepted an unscoped recursive manifest")


def test_v61_copy_counter_does_not_count_generated_h5(tmp_path):
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


def test_v61_actual_v60_graph_builds_405_scope_and_rebases_all_actionable_modules(tmp_path):
    module = _load()
    external = tmp_path / "external"
    external.mkdir()
    output_request = tmp_path / "v61-request.json"
    target = external / "v61" / "bundle-target"
    output = external / "v61" / "products"
    supervisor = external / "v61" / "supervisor"
    ledger = json.loads(
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
        .read_text(encoding="utf-8")
    )
    # The builder reads the live ledger but does not mutate it or read the raw
    # payload.  Use a real copy of its small metadata under the test root.
    ledger_path = tmp_path / "resource-ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    result = module.build_request(
        v60_request=V60_REQUEST,
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
    assert request["raw_source"]["scope"] == "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V61"
    embedded = request["embedded_worker_request"]
    for role, item in embedded["modules"].items():
        assert str(target / "runtime/native") in item["path"]
        assert all(stale not in item["path"] for stale in ("V58", "V58D", "V59", "V59B"))
        assert item["sha256"] == embedded["v61_worker_binding"]["module_sha256"][role]
    wrapper = next(item for item in request["runtime"]["code_overlay_bindings"]
                   if item["role"] == "v61_worker_wrapper")
    assert Path(wrapper["source_path"]).name == "ds_data02_stage2_f2_native_raw_to_typed_label_v61.py"
    assert Path(wrapper["target_path"]).name == Path(wrapper["source_path"]).name
    assert len(request["source_closure"]) == len(embedded["source_files"]) + len(
        embedded["v15_request"]["motion_engine_sources"])
    assert module._validate_request(output_request, verify_static=False)["scope_paths"] == request["raw_source"]["scope_paths"]


def test_v61_worker_binding_uses_real_worker_cli_and_bounded_failure_summary(tmp_path):
    module = _load()
    assert module.WORKER_SCRIPT != module.SCRIPT
    assert module.WORKER_SCRIPT.name == "ds_data02_stage2_f2_native_raw_to_typed_label_v61.py"
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


def test_v61_source_closure_is_after_reservation_and_rejects_wrong_sha(tmp_path):
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
    except module.PortableV61Error as error:
        assert "source closure SHA differs" in str(error)
    else:  # pragma: no cover
        raise AssertionError("wrong source closure SHA was accepted")


def test_v61_embedded_module_declared_sha_must_equal_expected_binding(tmp_path):
    module = _load()
    external = tmp_path / "external"
    external.mkdir()
    output_request = tmp_path / "v61-request.json"
    ledger = json.loads(
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
        .read_text(encoding="utf-8")
    )
    ledger_path = tmp_path / "resource-ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    module.build_request(
        v60_request=V60_REQUEST,
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
    mutated = tmp_path / "mutated-v61.json"
    mutated.write_text(json.dumps(request), encoding="utf-8")
    try:
        module._validate_request(mutated, verify_static=False)
    except module.PortableV61Error as error:
        assert "does not match expected binding" in str(error)
    else:  # pragma: no cover
        raise AssertionError("module SHA mismatch was accepted")
