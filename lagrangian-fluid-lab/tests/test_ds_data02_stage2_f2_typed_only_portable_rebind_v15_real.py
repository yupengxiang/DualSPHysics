"""Real copied V15 -> V2 -> V8/V12/scorer subprocess coverage.

This reuses the existing small manufactured V16 fixture, but changes the
sealed copied entrypoint to V15 and adds the separately copied V2 core sibling
that V15 imports.  The fixture is independent of production CURRENT336,
H5/BI4, and ROOT242 payloads.
"""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
REAL_TEST = ROOT / "tests" / (
    "test_ds_data02_stage2_f2_typed_only_portable_rebind_v2_real.py")
V15_SOURCE = SCRIPTS / (
    "ds_data02_stage2_f2_typed_only_portable_rebind_v15.py")
V2_SOURCE = SCRIPTS / (
    "ds_data02_stage2_f2_typed_only_portable_rebind_v2.py")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _ScriptResolver:
    """Keep the real fixture sources, replacing only the copied V2 role."""

    def __init__(self, source_dir: Path, v15_target_source: Path):
        self.source_dir = source_dir
        self.v15_target_source = v15_target_source

    def __truediv__(self, name: str) -> Path:
        if name == V2_SOURCE.name:
            return self.v15_target_source
        return SCRIPTS / name


def test_v15_real_copied_runtime_loads_v8_v12_and_scorer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = _load(REAL_TEST, "ds02_v15_real_v2_fixture")

    # The V15 source is copied under the historical V7 target name.  Its
    # sibling V2 core keeps its normal target name, so V15 cannot accidentally
    # import itself when it resolves SCRIPT.with_name(V2_NAME).
    v15_target_source = tmp_path / (
        "ds_data02_stage2_f2_typed_only_portable_rebind_v7.py")
    shutil.copyfile(V15_SOURCE, v15_target_source)
    monkeypatch.setattr(
        real, "S", _ScriptResolver(tmp_path, v15_target_source))

    original_build_contract = real.V1.build_contract
    observed: dict[str, object] = {}

    def build_contract_with_v2_core(*args, **kwargs):
        manifest_path = Path(kwargs["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        artifacts = list(manifest["artifacts"])
        if not any(item.get("logical_role") == "portable_rebind_v2_core"
                   for item in artifacts):
            value = V2_SOURCE.stat()
            artifacts.append({
                "logical_role": "portable_rebind_v2_core",
                "source_kind": "runtime_source_sibling",
                "source_path_provenance": str(V2_SOURCE),
                "source_sha256": real.V1._sha(V2_SOURCE),
                "source_sha256_basis": "V15_REAL_FIXTURE",
                "source_stat_provenance": {
                    "bytes": value.st_size,
                    "mode_bits": value.st_mode & 0o7777,
                    "mtime_ns": value.st_mtime_ns,
                    "ctime_ns": value.st_ctime_ns,
                    "st_dev": value.st_dev,
                    "st_ino": value.st_ino,
                },
                "target_relative_path": "runtime/" + V2_SOURCE.name,
                "target_stat": None,
                "target_sha256": None,
                "content_sha_verified": False,
                "content_verification_phase": "REBOUND_METADATA",
                "deferred_content": False,
                "placeholder_only": False,
                "actionable": True,
                "content_read_by_manifest": True,
            })
            manifest["artifacts"] = artifacts
            manifest["sha256"] = real.V1._canonical(manifest)
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n",
                encoding="utf-8")
        entry = next(item for item in manifest["artifacts"]
                     if item.get("logical_role") == "portable_rebind_v2_entrypoint")
        observed["entrypoint_source"] = entry["source_path_provenance"]
        observed["entrypoint_target"] = entry["target_relative_path"]
        observed["v2_core_present"] = any(
            item.get("logical_role") == "portable_rebind_v2_core"
            for item in manifest["artifacts"])
        return original_build_contract(*args, **kwargs)

    monkeypatch.setattr(real.V1, "build_contract", build_contract_with_v2_core)

    # The existing test invokes the real copied V8/V12/scorer subprocess and
    # checks its report/stream/stat contract.  Its first guard now executes
    # the V15 target; the later ROOT213 check remains an independent baseline.
    real.test_v2_real_relocated_v8_v12_typed_scorer_without_source(tmp_path)
    assert observed["entrypoint_source"] == str(v15_target_source)
    assert observed["entrypoint_target"] == (
        "runtime/ds_data02_stage2_f2_typed_only_portable_rebind_v7.py")
    assert observed["v2_core_present"] is True
