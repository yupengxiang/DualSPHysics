from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v48 = _load("ds02_v48_for_v49_test", SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v48.py")
v49 = _load("ds02_v49_test", SCRIPT_DIR / "ds_data02_stage2_f2_portable_executor_v49.py")
v48_tests = _load(
    "ds02_v48_fixture_for_v49_test",
    Path(__file__).with_name("test_ds_data02_stage2_f2_portable_executor_v48.py"),
)


def test_v49_rebinds_v48_to_bounded_v4_wrapper_and_recomputes_bytes(tmp_path: Path) -> None:
    request, overlay, old_wrapper, _root = v48_tests._fixture(tmp_path)
    v48_request = tmp_path / "v48" / "request.json"
    v48_overlay = tmp_path / "v48" / "overlay.json"
    first = v48.build_forward(
        v47_request=request,
        v47_overlay=overlay,
        scratch_worker=old_wrapper,
        output_request=v48_request,
        output_overlay=v48_overlay,
        target_root=tmp_path / "v48-target",
        output_root=tmp_path / "v48-output",
    )
    assert first["status"] == "READY_FOR_PARENT_V48_METADATA_GUARD"

    wrapper = SCRIPT_DIR / "ds_data02_stage2_f2_native_raw_to_typed_label_v4.py"
    result = v49.build_forward(
        v48_request=v48_request,
        v48_overlay=v48_overlay,
        scratch_worker=wrapper,
        output_request=tmp_path / "v49" / "request.json",
        output_overlay=tmp_path / "v49" / "overlay.json",
        target_root=tmp_path / "v49-target",
        output_root=tmp_path / "v49-output",
    )
    assert result["status"] == "READY_FOR_PARENT_V49_METADATA_GUARD"
    new_request = json.loads((tmp_path / "v49" / "request.json").read_text())
    new_overlay = json.loads((tmp_path / "v49" / "overlay.json").read_text())
    assert new_request["sha256"] == v49._canonical_sha(new_request)
    assert new_overlay["sha256"] == v49._canonical_sha(new_overlay)
    scratch = new_request["execution"]["decoder_scratch"]
    assert scratch["wrapper_schema"].endswith("wrapper.v4")
    assert scratch["max_frame_scratch_bytes"] == 512 * 1024 * 1024
    assert scratch["decoder_timeout_seconds"] == 180.0
    assert scratch["cleanup_failure"].startswith("terminal failure")
    binding = new_request["forward_v49"]["wrapper_binding"]
    assert binding["new_wrapper_sha256"] == v49._sha256_file(wrapper)
    assert binding["wrapper_byte_delta"] == binding["new_wrapper_bytes"] - binding["previous_wrapper_bytes"]
    assert new_request["forward_v49"]["static_copy_bytes_after_rebind"] > 0
    assert new_overlay["forward_v49"]["preserved_v2_runtime_bindings"] == []
    stale_root = str(tmp_path / "consumer")
    assert all(stale_root not in str(entry["original_path"]) for entry in new_overlay["entries"])


def test_v49_requires_consumed_v48_marker(tmp_path: Path) -> None:
    request, overlay, wrapper, _root = v48_tests._fixture(tmp_path)
    bad = json.loads(request.read_text())
    bad["sha256"] = v49._canonical_sha(bad)
    request_bad = tmp_path / "bad-request.json"
    request_bad.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(v49.PortableV49Error, match="V48 request lacks"):
        v49.build_forward(
            v48_request=request_bad,
            v48_overlay=overlay,
            scratch_worker=wrapper,
            output_request=tmp_path / "bad-out" / "request.json",
            output_overlay=tmp_path / "bad-out" / "overlay.json",
            target_root=tmp_path / "bad-target",
            output_root=tmp_path / "bad-output",
        )
