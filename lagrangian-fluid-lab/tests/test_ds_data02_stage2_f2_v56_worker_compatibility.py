from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v56.py"
PLAIN = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
WRAPPER = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v4.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


def _module():
    spec = importlib.util.spec_from_file_location("v56_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundle(tmp_path: Path):
    sources = tmp_path / "bundle" / "sources"
    runtime = tmp_path / "bundle" / "runtime" / "runtime" / "native"
    sources.mkdir(parents=True)
    runtime.mkdir(parents=True)
    wrapper = sources / "0029-ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
    plain = runtime / "ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
    shutil.copyfile(WRAPPER, wrapper)
    shutil.copyfile(PLAIN, plain)
    row = {"role": "raw_worker_v2", "target_path": str(plain), "sha256": _sha(plain),
           "bytes": plain.stat().st_size, "mode_bits": stat.S_IMODE(plain.stat().st_mode)}
    request = {"runtime_sources": [row],
               "execution": {"decoder_scratch": {"wrapper_sha256": _sha(wrapper)}}}
    return sources, plain, request


def test_v56_copies_plain_worker_and_real_v4_path_smoke(tmp_path):
    module = _module()
    sources, plain, request = _bundle(tmp_path)
    record = module._materialize_worker_compatibility(request, sources)
    target = Path(record["target_path"])
    assert target == tmp_path / "bundle" / "runtime" / "native" / module.WORKER_NAME
    assert target.is_file() and not target.is_symlink()
    assert target.read_bytes() == plain.read_bytes()
    assert (target.stat().st_dev, target.stat().st_ino) != (plain.stat().st_dev, plain.stat().st_ino)
    smoke = module._smoke_worker(PYTHON, request, [{"worker_parent": str(sources)}])
    assert smoke["status"] == "PASS_COPIED_V4_WORKER_PATH_AND_LOAD"
    assert smoke["worker_path"] == str(target.resolve())
    assert smoke["payload_read"] is False


def test_v56_rejects_original_worker_source(tmp_path):
    module = _module()
    sources, _plain, request = _bundle(tmp_path)
    request["runtime_sources"][0]["target_path"] = str(PLAIN)
    with pytest.raises(module.PortableV56Error, match="outside bundle"):
        module._materialize_worker_compatibility(request, sources)


def test_v56_rejects_hardlink_or_wrong_existing_compatibility(tmp_path):
    module = _module()
    sources, plain, request = _bundle(tmp_path)
    target = tmp_path / "bundle" / "runtime" / "native" / module.WORKER_NAME
    target.parent.mkdir(parents=True)
    target.hardlink_to(plain)
    with pytest.raises(module.PortableV56Error, match="shares source inode"):
        module._materialize_worker_compatibility(request, sources)


def test_v56_build_rebases_fresh_namespace_and_preserves_v55_provenance(tmp_path):
    module = _module()
    source = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v55-root145-source-prepared-20261009/f2-s1-root145-v55-executor-request.json"
    if not source.is_file():
        pytest.skip("V55 source-bound request is not present in this checkout")
    output = tmp_path / "v56-request.json"
    target = tmp_path / "target"
    product = tmp_path / "products"
    result = module.build_forward(v55_request=source, output_request=output,
                                  target_root=target, output_root=product)
    value = json.loads(output.read_text())
    assert result["schema"] == module.V56_SCHEMA
    assert value["sha256"] == module.canonical_sha(value)
    assert value["forward_v56"]["previous_request"]["path"] == str(source)
    assert value["fresh_roots"] == {"target_root": str(target), "output_root": str(product)}
    assert value["execution"]["worker_compatibility_target_relative_path"].endswith(module.WORKER_NAME)
    assert all(str(target) in row["target_path"] for row in value["runtime_sources"]
               if isinstance(row, dict) and isinstance(row.get("target_path"), str))


def test_root145_source_only_graph_exposes_missing_compatibility_target():
    module = _module()
    namespace = Path("/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT145_V55_RELOCATED_COLD_20261009")
    products = namespace / "products"
    inputs = [products / name for name in (
        "sealed-overlay-v34.json", "private-import-closure-v40.json",
        "private-runtime-audit-v34.json", "v40-engine-binding-before-label.json")]
    if not all(path.is_file() for path in inputs):
        pytest.skip("ROOT145 copied source-only evidence is not present")
    report = module.inspect_copied_graph(
        sealed_overlay=inputs[0], private_import_report=inputs[1],
        runtime_audit=inputs[2], engine_binding=inputs[3],
        bundle_root=namespace / "bundle-target")
    assert report["status"] == "FAILED_V4_COMPATIBILITY_TARGET_MISSING"
    assert report["payload_read"] is False
    assert report["v4_compatibility"]["ready"] is False
