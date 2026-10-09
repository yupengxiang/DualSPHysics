from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import stat

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_portable_executor_v57.py"
V4 = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v4.py"
PLAIN = ROOT / "scripts/ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
CONVERTER = ROOT / "scripts/ds_data02_f5_bi4.py"
V14 = ROOT / "scripts/ds_data02_stage2_f2_replay_v14.py"
V15 = ROOT / "scripts/ds_data02_stage2_f2_replay_v15.py"
V16 = ROOT / "scripts/ds_data02_stage2_f2_flux_v16.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
ROOT145 = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v55-root-forward-145-001")
BASE_EXECUTOR = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v55-root145-source-prepared-20261009/f2-s1-root145-v55-executor-request.json"


def _module():
    spec = importlib.util.spec_from_file_location("v57_test_module", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _code_bundle(tmp_path: Path):
    bundle = tmp_path / "bundle"
    sources = bundle / "sources"
    runtime_native = bundle / "runtime" / "runtime" / "native"
    sources.mkdir(parents=True)
    runtime_native.mkdir(parents=True)
    wrapper = sources / "0029-ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
    shutil.copyfile(V4, wrapper)
    plain = runtime_native / PLAIN.name
    shutil.copyfile(PLAIN, plain)
    modules = {
        "raw_converter": (CONVERTER, "ds_data02_f5_bi4.py"),
        "v14_operator": (V14, "ds_data02_stage2_f2_replay_v14.py"),
        "v15_operator": (V15, "ds_data02_stage2_f2_replay_v15.py"),
        "v16_operator": (V16, "ds_data02_stage2_f2_flux_v16.py"),
    }
    bindings = {}
    for role, (source, name) in modules.items():
        copied = runtime_native / name
        shutil.copyfile(source, copied)
        bindings[role] = {"path": str(copied), "sha256": _sha(copied),
                          "bytes": copied.stat().st_size,
                          "mode_bits": stat.S_IMODE(copied.stat().st_mode)}
    request = {
        "runtime_sources": [{"role": "raw_worker_v2", "target_path": str(plain),
                             "sha256": _sha(plain), "bytes": plain.stat().st_size,
                             "mode_bits": stat.S_IMODE(plain.stat().st_mode)}],
        "execution": {"decoder_scratch": {"wrapper_sha256": _sha(wrapper)}},
    }
    return bundle, sources, plain, request, bindings


def test_v57_plain_worker_lazy_graph_is_real_code_smoke(tmp_path):
    module = _module()
    bundle, sources, plain, request, bindings = _code_bundle(tmp_path)
    records = module._ORIGINAL_V55_ALIAS(bindings, sources)
    module.V56._materialize_worker_compatibility(request, sources)
    smoke = module.smoke_plain_worker_graph(PYTHON, request, records)
    assert smoke["status"] == "PASS_COPIED_PLAIN_WORKER_LAZY_IMPORT_GRAPH"
    assert smoke["payload_read"] is False
    assert Path(smoke["plain_worker"]) == bundle / "runtime" / "native" / PLAIN.name
    assert len(smoke["lazy_modules"]) == 4


def test_v57_inventory_separates_overlay_alias_parent_and_plain_parent(tmp_path):
    module = _module()
    bundle, sources, plain, request, bindings = _code_bundle(tmp_path)
    compatibility = bundle / "runtime" / "native" / PLAIN.name
    compatibility.parent.mkdir(parents=True)
    shutil.copyfile(plain, compatibility)
    aliases = {}
    for role, item in bindings.items():
        source = Path(item["path"])
        alias = sources / source.name
        shutil.copyfile(source, alias)
        aliases[role] = alias
    decoder = bundle / "sources" / "0023-bi4_dump"
    shutil.copyfile(DECODER, decoder)
    decoder.chmod(stat.S_IMODE(DECODER.stat().st_mode))
    report = module.inventory_code_graph(
        wrapper=sources / "0029-ds_data02_stage2_f2_native_raw_to_typed_label_v2.py",
        plain_worker=compatibility, aliases=aliases, decoder=decoder,
        bundle_root=bundle)
    assert report["status"] == "PASS_SOURCE_ONLY_COPIED_DEPENDENCY_INVENTORY"
    assert report["partvtk"]["worker_run_partvtk"] is False
    assert report["plain_worker"]["lazy_load_graph"] is True
    assert {Path(row["parent"]) for row in report["four_overlay_sibling_aliases"]} == {sources}


@pytest.mark.skipif(
    not (ROOT145 / "f2-s1-portable-parent-v55-root-145-receipt.json").is_file(),
    reason="ROOT145 receipt is not available in this checkout",
)
def test_v57_build_recovery_binds_separate_actual_receipt_and_returned_report(tmp_path):
    module = _module()
    base = BASE_EXECUTOR
    receipt = ROOT145 / "f2-s1-portable-parent-v55-root-145-receipt.json"
    returned = ROOT145 / "actual-returned-parent-report.json"
    output = tmp_path / "recovery-request.json"
    result = module.build_recovery(
        base_request=base, output_request=output,
        target_root=tmp_path / "target", output_root=tmp_path / "products",
        prior_parent_receipt=receipt, prior_returned_report=returned)
    value = json.loads(output.read_text())
    assert result["schema"] == module.RECOVERY_SCHEMA
    assert value["sha256"] == module._canonical(value)
    assert value["forward_v57"]["parent_receipt_returned_report_split"]["synthetic_combined_report_forbidden"]
    assert value["forward_v57"]["previous_v55_parent_receipt"]["path"] == str(receipt)
    assert value["forward_v57"]["previous_v55_returned_report"]["path"] == str(returned)
    assert value["storage_scope"]["source_copy_bytes"] == 0
    assert value["execution"]["command"][-1] == "6000"


@pytest.mark.skipif(
    not (ROOT145 / "f2-s1-portable-parent-v55-root-145-receipt.json").is_file(),
    reason="ROOT145 receipt is not available in this checkout",
)
def test_v57_rejects_combined_or_mismatched_parent_reports(tmp_path):
    module = _module()
    base = BASE_EXECUTOR
    receipt = ROOT145 / "f2-s1-portable-parent-v55-root-145-receipt.json"
    returned = ROOT145 / "actual-returned-parent-report.json"
    with pytest.raises(module.PortableV57Error, match="separate files"):
        module.build_recovery(
            base_request=base, output_request=tmp_path / "same.json",
            target_root=tmp_path / "t1", output_root=tmp_path / "p1",
            prior_parent_receipt=receipt, prior_returned_report=receipt)
    altered = json.loads(returned.read_text())
    altered["request_sha256"] = "0" * 64
    bad = tmp_path / "bad-returned.json"
    bad.write_text(json.dumps(altered))
    with pytest.raises(module.PortableV57Error, match="not bound"):
        module.build_recovery(
            base_request=base, output_request=tmp_path / "bad.json",
            target_root=tmp_path / "t2", output_root=tmp_path / "p2",
            prior_parent_receipt=receipt, prior_returned_report=bad)


def test_v57_run_delegates_through_v55_boundary_without_recursion(tmp_path, monkeypatch):
    """Exercise the installed hooks through a V55.run-style delegate.

    This stays code-only: the delegate invokes the real V55 alias/import
    callables on a synthetic copied bundle, but never enters the scientific
    child or opens BI4/HDF5/result data.  It catches the V56 failure mode in
    which a wrapper called the attribute it had just replaced.
    """
    module = _module()
    bundle, sources, plain, _, bindings = _code_bundle(tmp_path)
    wrapper = sources / "0029-ds_data02_stage2_f2_native_raw_to_typed_label_v2.py"
    request = {
        "schema": module.V34_SCHEMA,
        "forward_v55": {"schema": module.V55.FORWARD_SCHEMA},
        "forward_v57": {"schema": module.V57_SCHEMA},
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": dict(module.UNKNOWN),
        "fresh_roots": {"target_root": str(bundle / "target"),
                         "output_root": str(bundle / "products")},
        "runtime_sources": [{
            "role": "raw_worker_v2", "target_path": str(plain),
            "sha256": _sha(plain), "bytes": plain.stat().st_size,
            "mode_bits": stat.S_IMODE(plain.stat().st_mode),
        }],
        "execution": {"decoder_scratch": {"wrapper_sha256": _sha(wrapper)}},
    }
    request["sha256"] = module._canonical(request)
    request_path = tmp_path / "v57-run-request.json"
    request_path.write_text(json.dumps(request, sort_keys=True), encoding="utf-8")

    original_alias = module.V55._materialize_aliases_in_worker_parent
    original_import = module.V55._import_four_modules
    calls = []

    def delegated_v55_run(path, **kwargs):
        calls.append(str(path))
        records = module.V55._materialize_aliases_in_worker_parent(bindings, sources)
        imported = module.V55._import_four_modules(PYTHON, records)
        return {"status": "PASS_DELEGATED_V55_BOUNDARY",
                "record_count": len(records),
                "imported": imported}

    monkeypatch.setattr(module.V55, "run", delegated_v55_run)
    result = module.run(request_path, io_slot_approved=True, max_wall_seconds=5.0)
    assert result["status"] == "PASS_DELEGATED_V55_BOUNDARY"
    assert result["record_count"] == 4
    assert result["imported"]["all_four_modules_colocated"] is True
    assert calls == [str(request_path)]
    assert module.V55._materialize_aliases_in_worker_parent is original_alias
    assert module.V55._import_four_modules is original_import
