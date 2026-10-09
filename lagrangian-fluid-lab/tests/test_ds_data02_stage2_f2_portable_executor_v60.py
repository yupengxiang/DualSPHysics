from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v60.py"
V59_REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/native-reconstruction/"
    "raw-to-label-v59-root145-recovery-source-prepared-20261009/"
    "f2-s1-root145-v59b-parent-recovery-request.json"
)


def _load():
    spec = importlib.util.spec_from_file_location("v60_test_module", SCRIPT)
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


def test_v60_manifest_is_exact_producer_scope_and_ignores_bundle_code(tmp_path):
    module, root, scope, observed = _raw_fixture(tmp_path)
    checked = module._raw_tree_manifest(root, scope, observed["tree_sha256"])
    assert checked["file_count"] == 6
    assert checked["tree_sha256"] == observed["tree_sha256"]
    assert all(item["path"] in scope for item in checked["files"])
    try:
        module._raw_tree_manifest(root)
    except module.PortableV60Error as error:
        assert "explicit producer scope" in str(error)
    else:  # pragma: no cover
        raise AssertionError("V60 accepted an unscoped recursive manifest")


def test_v60_copy_counter_does_not_count_generated_h5(tmp_path):
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


def test_v60_actual_v59_graph_builds_405_scope_and_rebases_all_actionable_modules(tmp_path):
    module = _load()
    external = tmp_path / "external"
    external.mkdir()
    output_request = tmp_path / "v60-request.json"
    target = external / "v60" / "bundle-target"
    output = external / "v60" / "products"
    supervisor = external / "v60" / "supervisor"
    ledger = json.loads(
        Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
        .read_text(encoding="utf-8")
    )
    # The builder reads the live ledger but does not mutate it or read the raw
    # payload.  Use a real copy of its small metadata under the test root.
    ledger_path = tmp_path / "resource-ledger.json"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    result = module.build_request(
        v59_request=V59_REQUEST,
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
    assert request["raw_source"]["scope"] == "TOP_LEVEL_PRODUCER_RAW_EXPLICIT_V60"
    embedded = request["embedded_worker_request"]
    for role, item in embedded["modules"].items():
        assert str(target / "runtime/native") in item["path"]
        assert all(stale not in item["path"] for stale in ("V58", "V58D", "V59", "V59B"))
    assert module._validate_request(output_request, verify_static=False)["scope_paths"] == request["raw_source"]["scope_paths"]

